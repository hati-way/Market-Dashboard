"""modules/quality_gate 테스트.

실제 Anthropic API는 호출하지 않는다. WordPressArticle/MasterContent를
직접 만들어서 run_quality_gate()/각 score_*.py/decide_publication()을
검증한다.
"""
from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content
from modules.master_content.schema import (
    Analysis,
    ConfidenceLevel,
    Fact,
    MasterContent,
    Source,
    SourceType,
)
from modules.quality_gate import DEFAULT_CONFIG, GateStatus, decide_publication, run_quality_gate
from modules.quality_gate.aeo_score import score_aeo
from modules.quality_gate.geo_score import score_geo
from modules.quality_gate.models import PublicationDecision, QualityGateResult, RecommendedStatus, ScoreBreakdown
from modules.quality_gate.neo_score import score_neo
from modules.quality_gate.seo_score import score_seo
from modules.wordpress_writer.fact_validation import FactValidationResult, FactValidationStatus
from modules.wordpress_writer.markdown_html import markdown_to_html
from modules.wordpress_writer.models import WordPressArticle

SAMPLE_INPUT = "data/input/sample_market_data.json"


def _content_with_fact() -> tuple[MasterContent, Fact]:
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="미국 근원 PCE와 금리 인하 경로", market_data=market_data)
    fact = Fact(
        claim="근원 PCE 물가지수가 4.25%로 발표되었다.",
        value=4.25,
        unit="%",
        date="2026-08-26",
        source="U.S. Bureau of Economic Analysis",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
    )
    content.analysis = Analysis(
        primary_question="이번 근원 PCE 발표가 금리 인하 경로에 어떤 영향을 주는가",
        facts=[fact],
        sources=[
            Source(name="U.S. Bureau of Economic Analysis", url="https://www.bea.gov", source_type=SourceType.PRIMARY)
        ],
        causal_chain=["PCE 둔화", "인하 기대 강화"],
    )
    return content, content.analysis.facts[0]


def _well_formed_markdown() -> str:
    return (
        "결론부터: 근원 PCE(물가지수)가 4.25%(2026-08-26 기준)로 발표되며 인하 기대가 강화되었다.\n\n"
        "## 무슨 일이 일어났나\n"
        "미국 근원 PCE(개인소비지출) 물가지수가 4.25%(2026-08-26 기준)로 발표되었다. "
        "이는 시장 예상과 대체로 부합하는 수준이다.\n\n"
        "## 왜 중요한가\n"
        "이 지표는 연준이 가장 중요하게 보는 물가 지표 중 하나다. 수치가 둔화되면 "
        "인하 기대가 강화되는 경향이 있다.\n\n"
        "## 인과관계\n"
        "물가 둔화에 따라 연준의 인하 사이클 기대가 강화되는 흐름이 이어지고 있다.\n\n"
        "## 핵심 숫자\n"
        "- 근원 PCE: 4.25%(2026-08-26 기준)\n\n"
        "## 관련 지표\n"
        "| 지표 | 값 |\n| --- | --- |\n| 근원 PCE | 4.25% |\n\n"
        "## 핵심 요약\n"
        "이번 발표는 인하 경로에 우호적인 신호로 해석된다."
    )


def _well_formed_article(fact_id: str) -> WordPressArticle:
    markdown = _well_formed_markdown()
    article = WordPressArticle(
        title="미국 근원 PCE 4.25% 발표와 금리 인하 경로",
        slug="us-core-pce-4-25-rate-outlook",
        excerpt="근원 PCE가 4.25%로 발표되며 금리 인하 기대가 강화되었다.",
        meta_description="2026년 8월 26일 발표된 미국 근원 PCE 물가지수 4.25%를 바탕으로 향후 금리 인하 경로를 정리한다.",
        content_markdown=markdown,
        primary_keyword="근원 PCE",
        related_keywords=["금리 인하", "연준"],
        used_fact_ids=[fact_id],
    )
    article.source_list = ["U.S. Bureau of Economic Analysis (https://www.bea.gov)"]
    sources_html = (
        "<h2>출처</h2>\n<ul><li>U.S. Bureau of Economic Analysis "
        '(<a href="https://www.bea.gov">https://www.bea.gov</a>)</li></ul>'
    )
    article.content_html = markdown_to_html(article.content_markdown) + "\n" + sources_html
    return article


def _passing_fact_result(used_fact_ids: list[str]) -> FactValidationResult:
    return FactValidationResult(status=FactValidationStatus.PASS, used_fact_ids=used_fact_ids)


# ---- 1. Fact FAIL + SEO 100 → 전체 FAIL ----


def test_fact_fail_overrides_perfect_seo():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)  # SEO/AEO/GEO/NEO 모두 만점 수준

    fail_fact_result = FactValidationResult(
        status=FactValidationStatus.FAIL,
        used_fact_ids=[],
        invalid_fact_ids=["fact_999"],
        unsupported_claims=["used_fact_ids에 존재하지 않는 Fact ID가 포함되어 있습니다: fact_999"],
    )

    result = run_quality_gate(article, content, fact_result=fail_fact_result)

    assert result.status == GateStatus.FAIL
    assert any("Fact Validation" in f for f in result.failures)


# ---- 2. Fact REVIEW_REQUIRED → 전체 REVIEW_REQUIRED ----


def test_fact_review_required_propagates():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)

    review_fact_result = FactValidationResult(
        status=FactValidationStatus.REVIEW_REQUIRED,
        used_fact_ids=[fact.id],
        warnings=["낮은 확신도(confidence=low)의 fact(fact_002)를 근거로 사용했습니다: ..."],
    )

    result = run_quality_gate(article, content, fact_result=review_fact_result)

    assert result.status == GateStatus.REVIEW_REQUIRED
    assert result.failures == []


# ---- 3. Fact PASS + 모든 점수 기준 통과 → PASS ----


def test_all_pass_yields_overall_pass():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)

    result = run_quality_gate(article, content)  # fact_result 자동 계산

    assert result.status == GateStatus.PASS
    assert result.failures == []
    assert result.scores.seo >= DEFAULT_CONFIG.seo_min
    assert result.scores.aeo >= DEFAULT_CONFIG.aeo_min
    assert result.scores.geo >= DEFAULT_CONFIG.geo_min
    assert result.scores.neo >= DEFAULT_CONFIG.neo_min
    assert result.scores.overall >= DEFAULT_CONFIG.overall_min


# ---- 4. title 없음 → FAIL ----


def test_missing_title_fails():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)
    article.title = ""

    result = run_quality_gate(article, content)

    assert result.status == GateStatus.FAIL
    assert any("title" in f for f in result.failures)


# ---- 5. meta description 없음 → SEO 감점 ----


def test_missing_meta_description_lowers_seo_score():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)
    article.meta_description = ""

    lane = score_seo(article, DEFAULT_CONFIG)

    assert lane.score < 100
    assert any("meta description" in r for r in lane.recommendations)


# ---- 6. 첫 문단 직접 답변 없음 → AEO 감점 ----


def test_missing_direct_answer_lowers_aeo_score():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)
    article.content_markdown = "## 핵심 숫자\n- 근원 PCE: 4.25%\n\n## 핵심 요약\n- 요약 항목\n"
    article.content_html = markdown_to_html(article.content_markdown)

    lane = score_aeo(article, content, DEFAULT_CONFIG)

    assert lane.score < 100
    assert any("직접 답변" in issue for issue in lane.issues)


# ---- 7. primary source 포함 → GEO 점수 반영 ----


def test_primary_source_used_avoids_geo_penalty():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)
    fact_result_with_primary = FactValidationResult(status=FactValidationStatus.PASS, used_fact_ids=[fact.id])

    lane_with_primary = score_geo(article, content, fact_result_with_primary, DEFAULT_CONFIG)

    # source_type=secondary인 fact만 사용한 경우와 비교
    # (facts 리스트에 직접 append하면 Analysis의 자동 채번 validator가 다시
    # 실행되지 않으므로, id를 직접 지정한다.)
    secondary_fact = Fact(
        id="fact_002",
        claim="일부 애널리스트는 추가 인하를 예상한다.",
        source="시장 컨센서스",
        source_type=SourceType.SECONDARY,
        confidence=ConfidenceLevel.MEDIUM,
    )
    content.analysis.facts.append(secondary_fact)
    fact_result_with_secondary_only = FactValidationResult(
        status=FactValidationStatus.PASS, used_fact_ids=[secondary_fact.id]
    )

    lane_with_secondary_only = score_geo(article, content, fact_result_with_secondary_only, DEFAULT_CONFIG)

    assert lane_with_primary.score > lane_with_secondary_only.score
    assert any("1차 출처" in r for r in lane_with_secondary_only.recommendations)


# ---- 8. low confidence fact → REVIEW_REQUIRED ----


def test_low_confidence_fact_leads_to_review_required_gate():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)

    # (facts 리스트에 직접 append하면 자동 채번 validator가 다시 실행되지
    # 않으므로 id를 직접 지정한다.)
    low_fact = Fact(
        id="fact_002",
        claim="일부 애널리스트는 추가 인하 가능성을 제기한다.",
        source="시장 컨센서스",
        source_type=SourceType.SECONDARY,
        confidence=ConfidenceLevel.LOW,
    )
    content.analysis.facts.append(low_fact)
    article.used_fact_ids = [fact.id, low_fact.id]

    result = run_quality_gate(article, content)  # fact_result를 내부에서 계산

    assert result.status == GateStatus.REVIEW_REQUIRED
    assert result.failures == []


# ---- 9. keyword stuffing → SEO/NEO 경고 ----


def test_keyword_stuffing_triggers_seo_and_neo_warnings():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)
    stuffed = " ".join(["근원 PCE"] * 40)  # 명백한 키워드 반복
    article.content_markdown = f"결론부터: {stuffed}\n\n## 핵심 요약\n{stuffed}\n"
    article.content_html = markdown_to_html(article.content_markdown)

    seo_lane = score_seo(article, DEFAULT_CONFIG)
    neo_lane = score_neo(article, content, DEFAULT_CONFIG)

    assert any("반복" in w for w in seo_lane.warnings)
    assert any("반복" in w for w in neo_lane.warnings)


# ---- 10. heading hierarchy 오류 ----


def test_heading_hierarchy_violation_detected():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)
    article.content_html = "<h3>세부 항목</h3><p>본문</p><h2>상위 항목</h2>"

    lane = score_seo(article, DEFAULT_CONFIG)

    assert any("heading" in issue.lower() or "순서" in issue for issue in lane.issues)


# ---- 11. 너무 긴 한국어 문단 → NEO warning ----


def test_long_paragraph_triggers_neo_warning():
    content, fact = _content_with_fact()
    article = _well_formed_article(fact.id)
    long_paragraph = "이 문단은 매우 깁니다. " * 40  # 350자 훌쩍 초과
    article.content_markdown = f"결론부터: 요약.\n\n{long_paragraph}\n"

    lane = score_neo(article, content, DEFAULT_CONFIG)

    assert any("문단" in w for w in lane.warnings)


# ---- 12. publication decision ----


def test_publication_decision_pass_maps_to_publish():
    result = QualityGateResult(status=GateStatus.PASS, scores=ScoreBreakdown(fact=100, seo=100, aeo=100, geo=100, neo=100, overall=100))
    decision = decide_publication(result)

    assert isinstance(decision, PublicationDecision)
    assert decision.publish_ready is True
    assert decision.recommended_status == RecommendedStatus.PUBLISH


def test_publication_decision_review_required_maps_to_draft():
    result = QualityGateResult(
        status=GateStatus.REVIEW_REQUIRED,
        scores=ScoreBreakdown(fact=90, seo=90, aeo=90, geo=90, neo=90, overall=90),
        warnings=["SEO 점수가 기준 미달입니다."],
    )
    decision = decide_publication(result)

    assert decision.publish_ready is False
    assert decision.recommended_status == RecommendedStatus.DRAFT


def test_publication_decision_fail_maps_to_blocked():
    result = QualityGateResult(
        status=GateStatus.FAIL,
        scores=ScoreBreakdown(fact=0, seo=100, aeo=100, geo=100, neo=100, overall=35),
        failures=["Fact Validation = FAIL"],
    )
    decision = decide_publication(result)

    assert decision.publish_ready is False
    assert decision.recommended_status == RecommendedStatus.BLOCKED
