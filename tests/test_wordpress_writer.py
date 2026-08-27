"""modules/wordpress_writer 테스트.

실제 Anthropic API는 호출하지 않는다 (conftest.py의 FakeLlmClient로
LlmClient.generate() 를 대체한다).
"""
import json

import pytest

from clients.llm_client import LlmFatalError
from modules.master_content.builder import build_master_content
from modules.master_content.schema import (
    Analysis,
    ConfidenceLevel,
    Fact,
    MasterContent,
    Source,
    SourceType,
)
from modules.wordpress_writer.generator import (
    HallucinationDetectedError,
    WordPressGenerationError,
    generate_wordpress_content,
)
from modules.wordpress_writer.markdown_html import markdown_to_html

from .conftest import FakeLlmClient

SAMPLE_INPUT = "data/input/sample_market_data.json"


def _content_with_analysis() -> MasterContent:
    from modules.data_ingest.ingest import load_market_data_from_json_file

    market_data = load_market_data_from_json_file(SAMPLE_INPUT)
    content = build_master_content(topic="미국 증시 브리핑", market_data=market_data)
    content.analysis = Analysis(
        primary_question="이번 PCE 발표가 금리 인하 경로에 어떤 영향을 주는가?",
        summary="근원 PCE가 예상치를 하회했다.",
        facts=[
            Fact(
                claim="근원 PCE 물가지수가 예상치를 하회했다.",
                value=2.6,
                unit="%",
                date="2026-08-26",
                source="U.S. Bureau of Economic Analysis",
                source_type=SourceType.PRIMARY,
                confidence=ConfidenceLevel.HIGH,
            ),
            Fact(
                claim="다음 FOMC에서 금리가 인하될 가능성이 있다.",
                value=None,
                source="시장 컨센서스",
                source_type=SourceType.SECONDARY,
                confidence=ConfidenceLevel.LOW,
            ),
        ],
        sources=[
            Source(name="Fed", url="https://www.federalreserve.gov", source_type=SourceType.PRIMARY),
            Source(name="U.S. Bureau of Economic Analysis", source_type=SourceType.PRIMARY),
        ],
        bull_case=["인하 사이클이 예상보다 빨리 시작될 수 있다."],
        bear_case=["고용지표가 강하게 나오면 되돌림이 발생할 수 있다."],
        confidence=ConfidenceLevel.MEDIUM,
    )
    return content


def _article_json(**overrides) -> str:
    data = {
        "title": "미국 근원 PCE와 금리 인하 경로 브리핑",
        "slug": "us-core-pce-rate-outlook",
        "excerpt": "근원 PCE 발표를 바탕으로 금리 인하 경로를 점검한다.",
        "meta_description": "근원 PCE 발표를 바탕으로 금리 인하 경로를 점검한 분석글이다.",
        "content_markdown": (
            "## 핵심 답변\n"
            "근원 PCE가 2.6%로 예상치를 하회하며 인하 기대가 강화되었다.\n\n"
            "## 핵심 숫자\n"
            "- 근원 PCE: 2.6% (2026-08-26 기준)\n\n"
            "## 무슨 일이 일어났나\n"
            "근원 PCE 물가지수가 시장 예상치를 하회했다.\n\n"
            "## Bull case\n"
            "- 인하 사이클이 예상보다 빨리 시작될 수 있다.\n\n"
            "## Bear case\n"
            "- 고용지표가 강하게 나오면 되돌림이 발생할 수 있다.\n\n"
            "## 핵심 요약\n"
            "시장은 다음 FOMC를 주시하고 있다."
        ),
        "primary_keyword": "근원 PCE",
        "related_keywords": ["금리 인하", "FOMC"],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ---- 1. 정상적인 MasterContent → WordPressArticle 생성 ----


def test_generate_wordpress_content_success():
    content = _content_with_analysis()
    fake_client = FakeLlmClient(_article_json())

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert result is content
    assert result.wordpress.title == "미국 근원 PCE와 금리 인하 경로 브리핑"
    assert result.wordpress.seo.focus_keyword == "근원 PCE"
    assert result.wordpress.seo.meta_description
    assert "<h2>" in result.wordpress.content_html
    assert result.wordpress.content_markdown


# ---- 2. 필수 필드 누락 응답 → 실패 ----


def test_missing_required_field_raises_generation_error():
    content = _content_with_analysis()
    data = json.loads(_article_json())
    del data["content_markdown"]
    fake_client = FakeLlmClient(json.dumps(data, ensure_ascii=False))

    with pytest.raises(WordPressGenerationError):
        generate_wordpress_content(content, llm_client=fake_client)


# ---- 3. 잘못된 JSON 응답 → 실패 ----


def test_invalid_json_response_raises_generation_error():
    content = _content_with_analysis()
    fake_client = FakeLlmClient("이것은 JSON이 아닙니다.")

    with pytest.raises(WordPressGenerationError):
        generate_wordpress_content(content, llm_client=fake_client)


# ---- 4. LLM API 오류 전파 ----


def test_llm_error_propagates():
    content = _content_with_analysis()

    class RaisingLlmClient:
        def generate(self, *args, **kwargs):
            raise LlmFatalError("Anthropic API 인증에 실패했습니다.")

    with pytest.raises(LlmFatalError):
        generate_wordpress_content(content, llm_client=RaisingLlmClient())


# ---- 5. source_list 생성 확인 ----


def test_source_list_is_built_from_master_content_not_llm():
    content = _content_with_analysis()
    # LLM이 준 source_list는 무시되어야 한다.
    fake_client = FakeLlmClient(_article_json(source_list=["LLM이 지어낸 가짜 출처"]))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert result.wordpress.source_list == [
        "Fed (https://www.federalreserve.gov)",
        "U.S. Bureau of Economic Analysis",
    ]
    assert "LLM이 지어낸 가짜 출처" not in result.wordpress.source_list
    assert "출처" in result.wordpress.content_html
    assert "Fed" in result.wordpress.content_html


# ---- 6. Markdown -> HTML 변환 ----


def test_markdown_to_html_supports_required_elements():
    markdown_text = (
        "## 소제목\n"
        "일반 문단입니다. **굵게** 표시와 [링크](https://example.com)를 포함합니다.\n\n"
        "### 하위 소제목\n\n"
        "- 목록 1\n"
        "- 목록 2\n\n"
        "1. 순서 1\n"
        "2. 순서 2\n\n"
        "> 인용문입니다.\n\n"
        "| 항목 | 값 |\n"
        "| --- | --- |\n"
        "| A | 1 |\n"
    )

    result = markdown_to_html(markdown_text)

    assert "<h2>소제목</h2>" in result
    assert "<h3>하위 소제목</h3>" in result
    assert "<strong>굵게</strong>" in result
    assert '<a href="https://example.com"' in result
    assert "<ul><li>목록 1</li><li>목록 2</li></ul>" in result
    assert "<ol><li>순서 1</li><li>순서 2</li></ol>" in result
    assert "<blockquote>" in result
    assert "<table>" in result and "<th>항목</th>" in result and "<td>A</td>" in result


def test_markdown_to_html_escapes_raw_html():
    result = markdown_to_html("일반 문단 안에 <script>alert(1)</script> 가 섞여 있다.")

    assert "<script>" not in result
    assert "&lt;script&gt;" in result


# ---- 7. low confidence 정보 처리 ----


def test_low_confidence_fact_is_passed_to_prompt():
    content = _content_with_analysis()
    fake_client = FakeLlmClient(_article_json())

    generate_wordpress_content(content, llm_client=fake_client)

    assert len(fake_client.calls) == 1
    prompt = fake_client.calls[0]["user_prompt"]
    assert '"confidence": "low"' in prompt
    assert "다음 FOMC에서 금리가 인하될 가능성이 있다." in prompt
    # 시스템 프롬프트에 낮은 확신도 사실을 확정적으로 쓰지 말라는 지침이 있는지도 확인한다.
    assert fake_client.calls[0]["system_prompt"] is not None
    assert "확정적으로 표현하지 않는다" in fake_client.calls[0]["system_prompt"]


# ---- 8. MasterContent에 없는 값을 LLM 응답이 포함했을 때 탐지/차단 ----


def test_hallucinated_number_is_detected_and_blocked():
    content = _content_with_analysis()
    before_title = content.wordpress.title  # 기본값("") 저장

    fabricated_markdown = (
        "## 핵심 답변\n"
        "S&P 500 지수가 9999.99까지 급등했다 (MasterContent에는 없는 수치).\n"
    )
    fake_client = FakeLlmClient(_article_json(content_markdown=fabricated_markdown))

    with pytest.raises(HallucinationDetectedError):
        generate_wordpress_content(content, llm_client=fake_client)

    # 잘못된 글은 MasterContent.wordpress 에 반영되지 않아야 한다.
    assert content.wordpress.title == before_title
