"""Fact Grounding 검증(modules/wordpress_writer/fact_validation.py) 테스트.

실제 Anthropic API는 호출하지 않는다. 대부분의 테스트는
validate_fact_grounding()을 직접 호출해서 검증 로직만 독립적으로
확인하고, source_list 관련 테스트만 generate_wordpress_content() 전체
흐름(가짜 LlmClient 주입)을 사용한다.
"""
import json

from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content
from modules.master_content.schema import (
    Analysis,
    ConfidenceLevel,
    Fact,
    MarketDataPoint,
    MasterContent,
    Source,
    SourceType,
)
from modules.wordpress_writer.fact_validation import FactValidationStatus, validate_fact_grounding
from modules.wordpress_writer.generator import generate_wordpress_content
from modules.wordpress_writer.models import WordPressArticle

from .conftest import FakeLlmClient

SAMPLE_INPUT = "data/input/sample_market_data.json"


def _content_with_facts() -> tuple[MasterContent, dict[str, Fact]]:
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="FOMC 브리핑", market_data=market_data)

    percent_fact = Fact(
        claim="기준금리가 4.25%로 동결되었다.",
        value=4.25,
        unit="%",
        date="2026-08-26",
        source="Federal Reserve",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
    )
    bp_fact = Fact(
        claim="이번 인하폭은 25bp였다.",
        value=25,
        unit="bp",
        date="2026-08-26",
        source="Federal Reserve",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
    )
    dollar_fact = Fact(
        claim="회사채 매입 프로그램 규모가 40억 달러로 발표되었다.",
        value=4,
        unit="billion",
        source="Fed 성명서",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
    )
    date_fact = Fact(
        claim="다음 FOMC 회의는 2026년 9월 9일이다.",
        source="FOMC 일정",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
        date="2026-09-09",
    )
    low_confidence_fact = Fact(
        claim="일부 애널리스트는 추가 인하 가능성을 제기한다.",
        source="시장 컨센서스",
        source_type=SourceType.SECONDARY,
        confidence=ConfidenceLevel.LOW,
    )

    content.analysis = Analysis(
        facts=[percent_fact, bp_fact, dollar_fact, date_fact, low_confidence_fact],
        sources=[Source(name="Bloomberg"), Source(name="Reuters")],
    )

    facts_by_key = {
        "percent": content.analysis.facts[0],
        "bp": content.analysis.facts[1],
        "dollar": content.analysis.facts[2],
        "date": content.analysis.facts[3],
        "low": content.analysis.facts[4],
    }
    return content, facts_by_key


def _make_article(*, content_markdown: str, used_fact_ids: list[str] | None = None) -> WordPressArticle:
    return WordPressArticle(
        title="FOMC 브리핑: 금리와 다음 일정",
        slug="fomc-briefing",
        excerpt="이번 FOMC 결정을 정리한다.",
        meta_description="이번 FOMC 결정과 다음 일정을 정리한 분석글이다.",
        content_markdown=content_markdown,
        primary_keyword="FOMC",
        related_keywords=["금리", "연준"],
        used_fact_ids=used_fact_ids or [],
    )


# ---- 1~2. 퍼센트 ----


def test_percent_matching_master_content_passes():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n기준금리는 4.25%로 동결되었다.\n",
        used_fact_ids=[facts["percent"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS
    assert result.unsupported_numbers == []


def test_percent_not_matching_master_content_fails():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n기준금리는 4.75%로 동결되었다.\n",
        used_fact_ids=[facts["percent"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.FAIL
    assert any("4.75" in item for item in result.unsupported_numbers)


def test_negative_index_change_percent_expressed_without_sign_passes():
    """실제 dry-run 회귀 케이스: market_data.indices의 change_percent가
    음수(-0.03)일 때, 본문 정규식(`\\d+(?:\\.\\d+)?%`)은 "-" 부호를 애초에
    캡처하지 못해 "0.03%"처럼 항상 부호 없이 추출된다. 이 값은
    MasterContent에 실제로 존재하므로(change_percent=-0.03) 근거 없는
    수치로 잘못 판정되면 안 된다.
    """
    content, facts = _content_with_facts()
    content.market_data.indices = [
        MarketDataPoint(name="미국 10년물 국채금리", value=4.05, change_percent=-0.03, unit="%"),
    ]
    article = _make_article(
        content_markdown="## 핵심 답변\n국채금리는 전일 대비 0.03%p 하락했다.\n",
        used_fact_ids=[facts["percent"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS
    assert result.unsupported_numbers == []


# ---- 3~4. bp ----


def test_bp_matching_master_content_passes():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 인하폭은 25bp였다.\n",
        used_fact_ids=[facts["bp"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS


def test_bp_not_matching_master_content_fails():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 인하폭은 50bp였다.\n",
        used_fact_ids=[facts["bp"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.FAIL
    assert any("50" in item and "bp" in item for item in result.unsupported_numbers)


# ---- 5~6. 금액 ----


def test_dollar_amount_matching_master_content_passes():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n프로그램 규모는 $4 billion 이다.\n",
        used_fact_ids=[facts["dollar"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS


def test_dollar_amount_not_matching_master_content_fails():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n프로그램 규모는 $6 billion 이다.\n",
        used_fact_ids=[facts["dollar"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.FAIL
    assert any("$6" in item or "6" in item for item in result.unsupported_numbers)


# ---- 7~8. 날짜 ----


def test_korean_date_matching_master_content_passes():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 앞으로 확인해야 할 지표\n다음 FOMC 회의는 2026년 9월 9일이다.\n",
        used_fact_ids=[facts["date"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS


def test_nonexistent_date_fails():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 앞으로 확인해야 할 지표\n다음 FOMC 회의는 2026년 10월 10일이다.\n",
        used_fact_ids=[facts["date"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.FAIL
    assert any("10월 10일" in item or "2026-10-10" in item for item in result.unsupported_numbers)


# ---- 9~10. Fact ID ----


def test_nonexistent_fact_id_fails():
    content, _facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n관련 내용을 정리한다.\n",
        used_fact_ids=["fact_999"],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.FAIL
    assert "fact_999" in result.invalid_fact_ids
    assert any("fact_999" in item for item in result.unsupported_claims)


def test_valid_used_fact_ids_pass():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n연준은 시장 예상대로 움직였다.\n",
        used_fact_ids=[facts["percent"].id, facts["bp"].id, facts["percent"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS
    # 중복은 제거된다.
    assert result.used_fact_ids == [facts["percent"].id, facts["bp"].id]


# ---- 11. 목록 번호 오인 방지 ----


def test_list_ordinals_are_not_treated_as_facts():
    content, facts = _content_with_facts()
    markdown = (
        "## 핵심 숫자\n"
        "1. 기준금리 4.25% 동결\n"
        "2. 인하폭 25bp\n"
        "3. 다음 회의는 2026년 9월 9일\n"
    )
    article = _make_article(
        content_markdown=markdown,
        used_fact_ids=[facts["percent"].id, facts["bp"].id, facts["date"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS
    assert result.unsupported_numbers == []


# ---- 12. confidence=low ----


def test_low_confidence_fact_triggers_review_required():
    content, facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 전망\n일부 애널리스트는 추가 인하 가능성을 제기한다.\n",
        used_fact_ids=[facts["low"].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.REVIEW_REQUIRED
    assert any("confidence=low" in w for w in result.warnings)


def test_empty_used_fact_ids_with_concrete_numbers_triggers_review_required():
    content, _facts = _content_with_facts()
    article = _make_article(
        content_markdown="## 핵심 답변\n기준금리는 4.25%로 동결되었다.\n",
        used_fact_ids=[],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.REVIEW_REQUIRED
    assert result.warnings


# ---- 13. source_list ----


def test_source_list_prioritizes_used_fact_sources():
    content, facts = _content_with_facts()
    article_data = {
        "title": "FOMC 브리핑: 금리와 다음 일정",
        "slug": "fomc-briefing",
        "excerpt": "이번 FOMC 결정을 정리한다.",
        "meta_description": "이번 FOMC 결정과 다음 일정을 정리한 분석글이다.",
        "content_markdown": (
            "## 핵심 답변\n기준금리는 4.25%로 동결되었고 인하폭은 25bp였다.\n"
        ),
        "primary_keyword": "FOMC",
        "related_keywords": ["금리"],
        "used_fact_ids": [facts["percent"].id, facts["bp"].id],
    }
    fake_client = FakeLlmClient(json.dumps(article_data, ensure_ascii=False))

    result_content = generate_wordpress_content(content, llm_client=fake_client)

    # percent/bp fact는 둘 다 source="Federal Reserve"이고 date도 같으므로
    # (기관명+기준일+URL로 만든 문자열이 완전히 같아) 중복 제거되어 하나만
    # 남고, analysis.sources(Bloomberg/Reuters)는 쓰이지 않아야 한다.
    # analysis.sources에 "Federal Reserve"라는 이름의 Source가 없어 URL을
    # 찾지 못하므로 "URL 미제공"으로 표시된다(URL을 임의로 만들지 않는다).
    assert result_content.wordpress.source_list == ["Federal Reserve — 2026-08-26 — URL 미제공"]
    assert not any("Bloomberg" in s for s in result_content.wordpress.source_list)
    assert not any("Reuters" in s for s in result_content.wordpress.source_list)
    assert result_content.wordpress.fact_validation_status == "PASS"


# ---- 14~20. 통화 스케일 정규화(만/억/조 ↔ million/billion/trillion) ----
# 실제 dry-run 회귀 케이스: sample_treasury_buyback.json의 macro_events
# (previous="280억 달러 규모", forecast="250억~300억 달러 규모")에서 나온
# "280억 달러"/"250억"이, 실제로 MasterContent 안에 있는 값인데도
# FactGroundingError로 잘못 막혔다. 원인은 두 가지였다: (1) 금액 허용
# 목록이 facts만 스캔하고 macro_events는 스캔하지 않았고, (2) million/
# billion/trillion ↔ 만/억/조 단위 등가 변환이 아예 없었다.


def _content_with_amount_fact(value: float, unit: str) -> tuple[MasterContent, Fact]:
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="통화 스케일 테스트", market_data=market_data)
    fact = Fact(
        claim=f"프로그램 규모가 {value} {unit}로 발표되었다.",
        value=value,
        unit=unit,
        date="2026-08-26",
        source="Test Source",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
    )
    content.analysis = Analysis(facts=[fact], sources=[Source(name="Test Source")])
    return content, content.analysis.facts[0]


def test_billion_usd_matches_eok_dollar_equivalent():
    """28 billion USD -> 280억 달러 = PASS."""
    content, fact = _content_with_amount_fact(28, "billion USD")
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 프로그램 규모는 280억 달러로 발표되었다.\n",
        used_fact_ids=[fact.id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS
    assert result.unsupported_numbers == []


def test_25_billion_usd_matches_250eok_dollar_equivalent():
    """25 billion USD -> 250억 달러 = PASS."""
    content, fact = _content_with_amount_fact(25, "billion USD")
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 프로그램 규모는 250억 달러로 발표되었다.\n",
        used_fact_ids=[fact.id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS


def test_billion_usd_does_not_match_eok_won_same_magnitude():
    """28 billion USD -> 280억 원 = FAIL (통화가 다르면 raw_value가 같아도 임의 환산하지 않는다)."""
    content, fact = _content_with_amount_fact(28, "billion USD")
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 프로그램 규모는 280억 원으로 발표되었다.\n",
        used_fact_ids=[fact.id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.FAIL
    assert any("280억 원" in item for item in result.unsupported_numbers)


def test_billion_usd_does_not_match_wrong_magnitude():
    """28 billion USD -> 300억 달러 = FAIL (통화는 맞지만 금액 자체가 근거와 다름)."""
    content, fact = _content_with_amount_fact(28, "billion USD")
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 프로그램 규모는 300억 달러로 발표되었다.\n",
        used_fact_ids=[fact.id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.FAIL
    assert any("300억 달러" in item for item in result.unsupported_numbers)


def test_fractional_billion_usd_matches_eok_dollar_equivalent():
    """1.5 billion USD -> 15억 달러 = PASS."""
    content, fact = _content_with_amount_fact(1.5, "billion USD")
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 프로그램 규모는 15억 달러로 발표되었다.\n",
        used_fact_ids=[fact.id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS


def test_ungrounded_decimal_number_still_fails_with_currency_scale_helper():
    """근거 없는 650.12는 통화 스케일 정규화 도입 이후에도 여전히 근거 없는 값으로
    남아 있어야 한다(만/억/조/million/billion/trillion 단위가 없으므로 통화 스케일
    검사 대상이 아니고, 이 값 자체는 HallucinationDetectedError의 1차 방어선
    담당이다 - 여기서는 통화 검사가 이 값을 잘못 통과시키지 않는지만 확인한다)."""
    content, fact = _content_with_amount_fact(28, "billion USD")
    article = _make_article(
        content_markdown="## 핵심 답변\n관련 국채 선물 가격은 650.12를 나타냈다.\n",
        used_fact_ids=[fact.id],
    )

    result = validate_fact_grounding(article, content)

    assert not any("650.12" in item for item in result.unsupported_numbers)


def test_currency_omitted_amount_passes_when_context_is_unambiguous():
    """통화가 생략된 "250억"도, MasterContent 전체에 통화 후보가 달러 하나뿐이면
    문맥상 명확하므로 PASS해야 한다(REVIEW_REQUIRED로 보내지 않는다)."""
    content, fact = _content_with_amount_fact(25, "billion USD")
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 프로그램 규모는 250억으로 발표되었다.\n",
        used_fact_ids=[fact.id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.PASS
    assert result.warnings == []


def test_currency_omitted_amount_triggers_review_required_when_ambiguous():
    """같은 raw_value를 서로 다른 통화(달러/원)로 나타내는 근거가 둘 다 있으면,
    통화가 생략된 언급은 어느 쪽인지 확정할 수 없으므로 PASS가 아니라
    REVIEW_REQUIRED로 보내야 한다(FAIL로 막지도 않는다)."""
    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="통화 스케일 테스트(모호)", market_data=market_data)
    usd_fact = Fact(
        claim="달러 표시 프로그램 규모가 250억 달러였다.",
        value=25,
        unit="billion USD",
        date="2026-08-26",
        source="Test Source A",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
    )
    krw_fact = Fact(
        claim="원화 표시 프로그램 규모가 250억 원이었다.",
        value=25,
        unit="billion 원",
        date="2026-08-26",
        source="Test Source B",
        source_type=SourceType.PRIMARY,
        confidence=ConfidenceLevel.HIGH,
    )
    content.analysis = Analysis(
        facts=[usd_fact, krw_fact],
        sources=[Source(name="Test Source A"), Source(name="Test Source B")],
    )
    article = _make_article(
        content_markdown="## 핵심 답변\n이번 프로그램 규모는 250억으로 발표되었다.\n",
        used_fact_ids=[content.analysis.facts[0].id, content.analysis.facts[1].id],
    )

    result = validate_fact_grounding(article, content)

    assert result.status == FactValidationStatus.REVIEW_REQUIRED
    assert result.unsupported_numbers == []
    assert any("250억" in item for item in result.warnings)


def test_treasury_buyback_fixture_macro_event_amounts_are_grounded():
    """실제 dry-run 회귀 케이스 재현: sample_treasury_buyback.json의
    macro_events(previous="280억 달러 규모", forecast="250억~300억 달러
    규모")에서 나온 "280억 달러"/"250억"/"300억 달러"를 본문이 그대로
    인용해도 더 이상 FactGroundingError가 발생하지 않아야 한다.
    """
    from modules.data_ingest.ingest import load_market_content_input_from_json_file

    input_data = load_market_content_input_from_json_file(
        "data/input/sample_treasury_buyback.json"
    )
    content = build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )
    article = _make_article(
        content_markdown=(
            "## 핵심 답변\n"
            "재무부는 이번 분기 바이백 규모를 300억 달러로 발표했다. 이는 시장 "
            "예상치인 250억~300억 달러 범위 상단이었고, 직전 분기의 280억 달러보다 "
            "늘어난 규모다.\n"
        ),
        used_fact_ids=["fact_001"],
    )

    result = validate_fact_grounding(article, content)

    assert result.status in (FactValidationStatus.PASS, FactValidationStatus.REVIEW_REQUIRED)
    assert result.unsupported_numbers == []
