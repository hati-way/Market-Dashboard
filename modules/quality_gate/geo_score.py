"""GEO(Generative Engine Optimization) 점수.

fire-your-seo-agency의 references/geo.md 중 "문단 단위 인용 가능성
= [주어+수치+기준일+출처]", "1차 소스 우선" 원칙을 가져왔다. 이 프로젝트는
이미 Fact(value/unit/date/source)와 Fact Grounding(used_fact_ids 검증)을
갖고 있으므로, GEO 점수는 그 결과를 그대로 재사용해서 "본문이 실제로
Fact에 근거하는가"를 잰다. llms.txt·AI 크롤러 robots.txt 정책 같은
사이트 인프라 항목은 검사하지 않는다(이유는
.claude/skills/fire-your-seo-agency/PROJECT_NOTES.md 참고).
"""
from __future__ import annotations

import re

from modules.master_content.schema import ConfidenceLevel, MasterContent, SourceType
from modules.wordpress_writer.fact_validation import FactValidationResult
from modules.wordpress_writer.models import WordPressArticle

from ._shared import first_prose_block, has_context_dependent_start
from .config import DEFAULT_CONFIG, QualityGateConfig
from .models import LaneScore

_FIGURE_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*(?:bp|bps)\b", re.IGNORECASE)
_DATE_MENTION_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{4}년|\d{1,2}월\s*\d{1,2}일")
_CAUSAL_RE = re.compile(r"따라서|이에 따라|그 결과|때문에|영향으로")
_HEDGE_RE = re.compile(r"수 있다|것으로 보인다|가능성이 있다|확인이 필요|추정된다")


def score_geo(
    article: WordPressArticle,
    content: MasterContent,
    fact_result: FactValidationResult,
    config: QualityGateConfig = DEFAULT_CONFIG,
) -> LaneScore:
    score = 100
    issues: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    has_figure = bool(_FIGURE_RE.search(article.content_markdown))
    has_date = bool(_DATE_MENTION_RE.search(article.content_markdown))
    if has_figure and not has_date:
        score -= 15
        issues.append("수치는 있지만 기준일이 함께 표기되지 않았습니다.")

    if not article.source_list:
        score -= 20
        issues.append("출처(source_list)가 비어 있습니다.")

    fact_by_id = {fact.id: fact for fact in content.analysis.facts if fact.id}
    used_facts = [fact_by_id[fid] for fid in fact_result.used_fact_ids if fid in fact_by_id]

    if not used_facts:
        score -= 20
        warnings.append("본문이 근거로 삼은 fact(used_fact_ids)가 없어 사실-출처 연결을 확인할 수 없습니다.")
    elif not any(fact.source_type == SourceType.PRIMARY for fact in used_facts):
        score -= 10
        recommendations.append("1차 출처(source_type=primary) fact를 우선 근거로 사용하는 것을 검토하세요.")

    if not (_CAUSAL_RE.search(article.content_markdown) or content.analysis.causal_chain):
        score -= 10
        recommendations.append("인과관계를 설명하는 문장(예: '따라서', '이에 따라')이 보이지 않습니다.")

    low_confidence_used = [fact for fact in used_facts if fact.confidence == ConfidenceLevel.LOW]
    if low_confidence_used and not _HEDGE_RE.search(article.content_markdown):
        score -= 15
        warnings.append(
            "확신도가 낮은(confidence=low) fact를 사용했지만 본문에 불확실성을 "
            "나타내는 표현이 보이지 않습니다."
        )

    if has_context_dependent_start(first_prose_block(article.content_markdown)):
        score -= 10
        issues.append("첫 문단이 맥락 의존적이어서 독립적으로 인용하기 어렵습니다.")

    score = max(0, min(100, score))
    return LaneScore(score=score, issues=issues, warnings=warnings, recommendations=recommendations)
