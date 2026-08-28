"""modules/wordpress_writer "생성 품질" 개선 회귀 테스트.

Fact Grounding/Quality Gate/WordPress Publisher 로직은 이 라운드에서
건드리지 않았다 - 이 파일은 그 판정 기준이 새 문체/구조에서도 그대로
작동하는지, 그리고 이번에 바꾼 부분(소제목 한글화, 출처 표기,
seo_title, 내부링크)이 의도대로 동작하는지만 확인한다.

실제 LLM 호출은 하지 않는다(FakeLlmClient). content_markdown은 새
시스템 프롬프트가 요구하는 구조/문체를 따르는 "모범 답안"을 직접
작성해 캔으로 주입한다 - 실제 LLM이 이 스타일을 따르는지는 이 테스트로
보장할 수 없지만, 파이프라인이 이 스타일을 올바르게 처리/보존하는지는
확인할 수 있다.
"""
import json

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.master_content.schema import InternalLink, Source, SourceType
from modules.quality_gate.seo_score import score_seo
from modules.wordpress_writer.fact_validation import FactValidationStatus
from modules.wordpress_writer.generator import HallucinationDetectedError, generate_wordpress_content
from modules.wordpress_writer.models import WordPressArticle

from .conftest import FakeLlmClient

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"

# 새 시스템 프롬프트가 요구하는 8단계 한글 구조 + 조건부 인과관계 +
# 저확신도 표현 규칙을 따르는 "모범 답안" 본문. sample_treasury_buyback.json
# 의 facts(fact_001~004)만 근거로 쓴다.
GOOD_STYLE_MARKDOWN = """## 핵심 답변
미국 재무부가 분기 국채 바이백 규모를 300억 달러로 확대하면서 장기금리가 소폭 낮아졌다.

## 무슨 일이 있었나
2026년 8월 27일 재무부는 분기 국채 바이백 규모를 300억 달러로 발표했다. 발표 직후 미국 10년물 국채금리는 4.05%로 내렸고, 같은 날 달러 인덱스(DXY)는 101.2를 기록하며 강보합세를 보였다. 바이백은 재무부가 시장에서 직접 국채를 사들여 특정 만기의 유통 물량을 줄이는 조치로, 이번 발표는 최근 몇 분기 중 상대적으로 큰 규모에 속한다.

## 왜 중요한가
바이백 자체의 절대 규모보다 중요한 건 재무부가 국채 시장의 어느 구간을 지원하려 하는지다. 유동성이 얇은 구간을 겨냥한 바이백은 그 구간의 매수·매도 스프레드를 좁히고, 발행 물량이 많은 시기에 시장이 흡수해야 할 부담을 분산시키는 효과를 낼 수 있다. 재무부의 국채 발행 및 유동성 관리 방향을 가늠할 수 있는 신호이기도 하고, 채권 딜러들의 재고 부담을 얼마나 덜어주는지에 따라 유통시장의 호가 형성 방식도 달라질 수 있다.

## 시장에 전달되는 경로
바이백 확대가 특정 만기의 유동성과 수급을 개선하면 유동성 프리미엄과 금리 변동성이 완화될 수 있고, 그 경우 위험자산에는 우호적인 환경이 형성될 수 있다. 국채금리가 낮아지는 방향으로 움직이면 할인율 부담이 줄어드는 경로로 주식시장에도 간접적으로 영향을 줄 수 있다. 다만 이 전달 경로는 자동으로 작동하지 않는다. 재정 발행 계획, 연준의 정책 기조, 해외 수요 같은 다른 변수와 함께 움직인다. 달러 인덱스의 강보합은 이 흐름과 크게 상충되지 않는 수준으로 해석되지만, 그 자체로 방향성을 확정 짓는 근거는 아니다. 여러 변수가 같은 방향을 가리킬 때만 이 경로가 뚜렷하게 확인될 가능성이 높다.

## 긍정적으로 볼 수 있는 이유
바이백이 유동성이 부족한 구간의 수급을 실제로 개선하면, 그 구간의 가격 변동성이 낮아지고 향후 발행에 대한 시장의 흡수 부담도 줄어들 수 있다. 딜러들의 재고 회전이 원활해지면 경매 결과에 대한 불확실성도 함께 줄어드는 흐름을 기대할 수 있다.

## 반대로 봐야 할 위험
바이백 규모가 다음 분기에 예상보다 더 커지면, 재정 적자 확대와 국채 발행 부담에 대한 우려가 다시 부각될 수 있다. 이 경우 지금과 반대로 장기금리에 상방 압력이 실릴 여지가 있고, 바이백이 오히려 재정 건전성에 대한 신호로 읽힐 수도 있다.

## 이 해석이 틀릴 수 있는 조건
재무부가 다음 발표에서 바이백 규모를 공식적으로 축소하거나, 지원 대상 만기 구간을 눈에 띄게 좁히면 이번 해석의 전제가 무너진다. 그 경우 이번 글에서 다룬 유동성 개선 경로도 함께 재검토해야 한다.

## 앞으로 확인할 지표
다음 분기 재융자 발표(QRA)에서 이번 기조가 이어지는지, 그리고 차기 국채 바이백 운영 일정에서 지원 대상 만기 구간이 어떻게 바뀌는지를 확인해야 한다.

## 핵심 요약
지금 자본이 보고 있는 건 바이백의 크기보다 재무부가 어느 만기를 지원하는지다. 시장은 아직 다음 QRA에서 이 기조가 이어질지를 가격에 온전히 반영하지 않았다. 일부 시장 참여자는 이번 조치가 장기물 발행 부담을 완화할 가능성이 있다고 보지만, 이는 복수 딜러 서베이에 기반한 해석으로 아직 확정된 결과는 아니다.
"""

GOOD_STYLE_ARTICLE = {
    "title": "미국 국채 바이백 300억 달러 확대, 시장에 어떤 의미일까",
    "seo_title": "미국 국채 바이백 300억 달러 확대와 장기금리 영향",
    "slug": "us-treasury-buyback-300-billion-expansion",
    "excerpt": "재무부의 분기 국채 바이백 확대가 채권·주식 시장에 미치는 영향을 정리한다.",
    "meta_description": "미국 재무부의 국채 바이백 확대 발표가 장기금리와 달러, 위험자산에 미치는 영향을 분석한다.",
    "content_markdown": GOOD_STYLE_MARKDOWN,
    "primary_keyword": "미국 재무부 바이백",
    "related_keywords": ["국채금리", "달러 인덱스"],
    "used_fact_ids": ["fact_001", "fact_002", "fact_003", "fact_004"],
}


def _load_treasury_content():
    input_data = load_market_content_input_from_json_file(EXTENDED_INPUT)
    return build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )


# ---- 1. Bull case / Bear case / thesis / invalidation 표현이 본문에 없음 ----


def test_no_english_subheadings_in_generated_body():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    for banned in ("Bull case", "Bear case", "bull case", "bear case", "thesis", "invalidation"):
        assert banned not in result.wordpress.content_markdown
        assert banned not in result.wordpress.content_html


# ---- 2. H1이 content_html 안에 중복 생성되지 않음 ----


def test_h1_is_never_duplicated_in_content_html():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert "<h1" not in result.wordpress.content_html.lower()


def test_h1_is_downgraded_even_if_llm_disobeys_and_uses_markdown_h1():
    """LLM이 지침을 어기고 "# 제목" 줄을 넣어도 h1 태그가 만들어지지 않는다
    (markdown_to_html이 '#'을 h2로 취급하는 기존 동작을 그대로 활용)."""
    content = _load_treasury_content()
    disobedient_markdown = "# 미국 국채 바이백 확대\n\n" + GOOD_STYLE_MARKDOWN
    fake_client = FakeLlmClient(
        json.dumps({**GOOD_STYLE_ARTICLE, "content_markdown": disobedient_markdown}, ensure_ascii=False)
    )

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert "<h1" not in result.wordpress.content_html.lower()


# ---- 3. 같은 핵심 숫자가 불필요하게 여러 섹션에서 반복되지 않음 ----


def test_key_market_figures_are_not_repeated_across_sections():
    """모범 답안 본문에서 10년물 금리(4.05%)와 DXY(101.2)는 "무슨 일이
    있었나" 한 곳에서만 언급되고, 다른 섹션에서 같은 수치를 다시 쓰지
    않는다(제목/첫 문단에서 발표 규모를 다시 언급하는 리드 관행은 별개로
    허용한다).
    """
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)
    markdown = result.wordpress.content_markdown

    assert markdown.count("4.05") == 1
    assert markdown.count("101.2") == 1


# ---- 4. confidence=low fact가 단정적으로 표현되지 않음 ----


def test_low_confidence_claim_uses_hedged_language():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)
    markdown = result.wordpress.content_markdown

    # fact_004(confidence=low, source_type=secondary)의 주장이 들어간 문장은
    # 주체("일부 시장 참여자")와 불확실성 표현("가능성이 있다고 본다")을
    # 함께 써야 한다 - "~한다"처럼 단정적으로 쓰면 안 된다.
    assert "일부 시장 참여자는" in markdown
    assert "가능성이 있다고" in markdown
    assert "장기물 발행 부담을 완화한다." not in markdown


# ---- 5~6. 출처 URL 표시 ----


def test_source_with_url_includes_link_in_source_list():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    # fact_001/fact_002의 source="U.S. Department of the Treasury"는
    # analysis.sources에 URL이 있으므로 source_list에 그 URL이 포함되어야 한다.
    assert any("https://home.treasury.gov/" in entry for entry in result.wordpress.source_list)


def test_source_url_is_rendered_as_clickable_link_in_content_html():
    """source_list의 URL은 <a> 태그로 렌더링된다(출처를 실제로 확인할 수
    있게 하고, Quality Gate의 "본문에 링크 없음" 권고도 실제 출처 URL로
    해소되게 한다). Quality Gate 자체(modules/quality_gate)는 건드리지
    않았다 - 이미 있는 <a> 태그 검사 로직을 그대로 만족시킬 뿐이다.
    """
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert '<a href="https://home.treasury.gov/"' in result.wordpress.content_html


def test_source_without_url_never_gets_a_fabricated_url():
    """analysis.sources에 URL이 없는 출처(fact_004의 "시장 컨센서스")는
    URL을 임의로 만들지 않고 "URL 미제공"으로 표시되며, 2차 출처라는
    한계도 함께 명시한다.
    """
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    consensus_entries = [e for e in result.wordpress.source_list if "시장 컨센서스" in e]
    assert len(consensus_entries) == 1
    assert "URL 미제공" in consensus_entries[0]
    assert "2차 출처" in consensus_entries[0]
    # http(s):// 로 시작하는 임의 URL이 붙어 있지 않아야 한다.
    assert "http://" not in consensus_entries[0]
    assert "https://" not in consensus_entries[0]


# ---- 7. 글 길이(1,500~2,500자) ----


def test_body_length_is_within_target_range():
    assert 1500 <= len(GOOD_STYLE_MARKDOWN) <= 2500


# ---- 8. 인과관계 문장이 조건부 표현을 유지 ----


def test_causal_chain_uses_conditional_phrasing_not_arrow_chain():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)
    markdown = result.wordpress.content_markdown

    # "A → B → C"처럼 화살표로 잇는 단정적 인과 표현을 쓰지 않는다.
    assert "→" not in markdown
    # 대신 조건부 표현("~하면", "~수 있다")을 실제로 쓴다.
    assert "완화될 수 있고" in markdown
    assert "형성될 수 있다" in markdown


# ---- 9. title 길이 과도 시 경고 (기존 Quality Gate, 미변경) ----


def test_overlong_title_still_triggers_existing_seo_recommendation():
    """title 길이 검사 자체는 modules/quality_gate/seo_score.py의 기존
    로직이다 - 이번 라운드에서 그 로직을 바꾸지 않았다는 것과, 새 title
    가이드(간결하게 쓰기)를 어기면 여전히 걸린다는 것만 함께 확인한다.
    """
    overlong_title = (
        "미국 재무부 국채 바이백 300억 달러 확대 발표가 채권시장과 주식시장, "
        "달러 환율 전반에 걸쳐 어떤 장기적 파급 효과를 가져올 것인지에 대한 심층 분석과 전망"
    )
    article = WordPressArticle(
        title=overlong_title,
        slug="us-treasury-buyback-deep-dive",
        excerpt="e",
        meta_description="m" * 60,
        content_markdown=GOOD_STYLE_MARKDOWN,
        content_html="<h2>x</h2><p>y</p>",
        primary_keyword="미국 재무부 바이백",
    )

    result = score_seo(article)

    assert any("제목 길이" in rec for rec in result.recommendations)


def test_concise_title_within_guideline_does_not_trigger_length_recommendation():
    article = WordPressArticle(
        title=GOOD_STYLE_ARTICLE["title"],
        slug="us-treasury-buyback-300-billion-expansion",
        excerpt="e",
        meta_description="m" * 60,
        content_markdown=GOOD_STYLE_MARKDOWN,
        content_html="<h2>x</h2><p>y</p><a href='https://example.com'>l</a>",
        primary_keyword="미국 재무부 바이백",
    )

    result = score_seo(article)

    assert not any("제목 길이" in rec for rec in result.recommendations)


# ---- 10. 기존 Fact Grounding은 그대로 작동 ----


def test_fact_grounding_still_passes_with_new_style_body():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert result.wordpress.fact_validation_status in ("PASS", "REVIEW_REQUIRED")


def test_fact_grounding_still_blocks_hallucination_with_new_style_body():
    content = _load_treasury_content()
    hallucinated_markdown = GOOD_STYLE_MARKDOWN.replace(
        "101.2를 기록하며", "101.2를 기록했고 관련 국채 선물 가격은 650.12를 나타내며"
    )
    fake_client = FakeLlmClient(
        json.dumps({**GOOD_STYLE_ARTICLE, "content_markdown": hallucinated_markdown}, ensure_ascii=False)
    )

    try:
        generate_wordpress_content(content, llm_client=fake_client)
        raised = False
    except HallucinationDetectedError:
        raised = True

    assert raised, "fixture에 없는 숫자(650.12)가 포함됐는데도 예외가 발생하지 않았다."


# ---- seo_title / title 분리 ----


def test_seo_title_is_used_for_meta_title_when_provided():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert result.wordpress.title == GOOD_STYLE_ARTICLE["title"]
    assert result.wordpress.seo.meta_title == GOOD_STYLE_ARTICLE["seo_title"]
    assert result.wordpress.seo.meta_title != result.wordpress.title


def test_seo_title_falls_back_to_title_when_empty():
    content = _load_treasury_content()
    article_without_seo_title = {**GOOD_STYLE_ARTICLE, "seo_title": ""}
    fake_client = FakeLlmClient(json.dumps(article_without_seo_title, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert result.wordpress.seo.meta_title == result.wordpress.title


# ---- 내부링크: 있으면 쓰고, 없으면 지어내지 않음 ----


def test_internal_links_are_rendered_when_present_in_master_content():
    content = _load_treasury_content()
    content.analysis.internal_links = [
        InternalLink(title="이전 분기 바이백 정리", url="https://example.com/prev-buyback")
    ]
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert "관련 글" in result.wordpress.content_html
    assert 'href="https://example.com/prev-buyback"' in result.wordpress.content_html


def test_no_internal_links_section_when_master_content_has_none():
    content = _load_treasury_content()
    assert content.analysis.internal_links == []
    fake_client = FakeLlmClient(json.dumps(GOOD_STYLE_ARTICLE, ensure_ascii=False))

    result = generate_wordpress_content(content, llm_client=fake_client)

    assert "관련 글" not in result.wordpress.content_html
