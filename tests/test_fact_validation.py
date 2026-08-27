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

    # percent/bp fact는 둘 다 source="Federal Reserve" 이므로 중복 제거되어
    # 하나만 남고, analysis.sources(Bloomberg/Reuters)는 쓰이지 않아야 한다.
    assert result_content.wordpress.source_list == ["Federal Reserve"]
    assert "Bloomberg" not in result_content.wordpress.source_list
    assert "Reuters" not in result_content.wordpress.source_list
    assert result_content.wordpress.fact_validation_status == "PASS"
