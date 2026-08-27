"""Quality Gate 통합 판정.

Fact Validation(modules/wordpress_writer/fact_validation) 결과가
언제나 SEO/AEO/GEO/NEO 점수보다 우선한다: Fact가 FAIL이면 점수가
아무리 높아도 전체 결과는 FAIL이다.

이 모듈은 WordPressArticle의 내용을 검사만 하고 수정하지 않는다.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent
from modules.wordpress_writer.fact_validation import (
    FactValidationResult,
    FactValidationStatus,
    validate_fact_grounding,
)
from modules.wordpress_writer.models import WordPressArticle

from .aeo_score import score_aeo
from .config import DEFAULT_CONFIG, QualityGateConfig
from .geo_score import score_geo
from .models import GateStatus, PublicationDecision, QualityGateResult, RecommendedStatus, ScoreBreakdown
from .neo_score import score_neo
from .seo_score import score_seo


def _compute_fact_score(fact_result: FactValidationResult) -> int:
    score = 100
    score -= 40 * len(fact_result.invalid_fact_ids)
    score -= 25 * len(fact_result.unsupported_numbers)
    score -= 10 * len(fact_result.warnings)
    return max(0, min(100, score))


def _compute_overall(fact: int, seo: int, aeo: int, geo: int, neo: int) -> int:
    weighted = fact * 0.35 + seo * 0.20 + aeo * 0.20 + geo * 0.15 + neo * 0.10
    return round(weighted)


def run_quality_gate(
    article: WordPressArticle,
    content: MasterContent,
    fact_result: FactValidationResult | None = None,
    config: QualityGateConfig = DEFAULT_CONFIG,
) -> QualityGateResult:
    """SEO/AEO/GEO/NEO 점수를 계산하고, Fact Grounding 결과와 합쳐
    PASS/REVIEW_REQUIRED/FAIL을 판정한다.

    fact_result를 넘기지 않으면 validate_fact_grounding()으로 직접
    계산한다. 이미 계산된 결과가 있으면(예: wordpress_writer가 생성
    직후 계산한 것) 그대로 넘겨서 중복 계산을 피할 수 있다.
    """
    if fact_result is None:
        fact_result = validate_fact_grounding(article, content)

    failures: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    # 필수 필드: 점수와 무관하게 항상 FAIL.
    if not article.title.strip():
        failures.append("필수 필드 누락: title이 비어 있습니다.")
    if not article.content_markdown.strip():
        failures.append("필수 필드 누락: content(본문)가 비어 있습니다.")

    # Fact Validation은 점수보다 우선한다.
    if fact_result.status == FactValidationStatus.FAIL:
        failures.append("Fact Validation = FAIL")
        failures.extend(fact_result.unsupported_claims)
        failures.extend(fact_result.unsupported_numbers)
    elif fact_result.status == FactValidationStatus.REVIEW_REQUIRED:
        warnings.extend(fact_result.warnings)

    fact_score = _compute_fact_score(fact_result)
    seo = score_seo(article, config)
    aeo = score_aeo(article, content, config)
    geo = score_geo(article, content, fact_result, config)
    neo = score_neo(article, content, config)

    for lane_name, lane, minimum in (
        ("SEO", seo, config.seo_min),
        ("AEO", aeo, config.aeo_min),
        ("GEO", geo, config.geo_min),
        ("NEO", neo, config.neo_min),
    ):
        warnings.extend(lane.warnings)
        recommendations.extend(lane.recommendations)
        if lane.issues:
            recommendations.extend(f"[{lane_name}] {issue}" for issue in lane.issues)
        if lane.score < minimum:
            warnings.append(f"{lane_name} 점수({lane.score})가 기준({minimum}) 미달입니다.")

    overall = _compute_overall(fact_score, seo.score, aeo.score, geo.score, neo.score)
    if overall < config.overall_min:
        warnings.append(f"overall 점수({overall})가 기준({config.overall_min}) 미달입니다.")

    scores = ScoreBreakdown(
        fact=fact_score, seo=seo.score, aeo=aeo.score, geo=geo.score, neo=neo.score, overall=overall
    )

    if failures:
        status: GateStatus = FactValidationStatus.FAIL
    elif warnings:
        status = FactValidationStatus.REVIEW_REQUIRED
    else:
        status = FactValidationStatus.PASS

    return QualityGateResult(
        status=status,
        scores=scores,
        failures=failures,
        warnings=warnings,
        recommendations=recommendations,
    )


def decide_publication(gate_result: QualityGateResult) -> PublicationDecision:
    """Quality Gate 결과로부터 발행 여부를 결정한다.

    실제 WordPress 발행(modules/wordpress_publisher)은 이 결과를 그대로
    가져다 쓸 수 있지만, 이번 단계에서는 결정 모델만 만들고 실제 발행에
    연결하지 않는다.
    """
    if gate_result.status == FactValidationStatus.PASS:
        return PublicationDecision(
            publish_ready=True,
            recommended_status=RecommendedStatus.PUBLISH,
            reason="Quality Gate PASS",
        )
    if gate_result.status == FactValidationStatus.REVIEW_REQUIRED:
        reason = "; ".join(gate_result.warnings) or "REVIEW_REQUIRED"
        return PublicationDecision(
            publish_ready=False,
            recommended_status=RecommendedStatus.DRAFT,
            reason=reason,
        )
    reason = "; ".join(gate_result.failures) or "FAIL"
    return PublicationDecision(
        publish_ready=False,
        recommended_status=RecommendedStatus.BLOCKED,
        reason=reason,
    )
