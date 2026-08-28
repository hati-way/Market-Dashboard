"""data/input/sample_treasury_buyback.json 확장 입력 fixture를 사용한
파이프라인 통합 테스트.

이 fixture는 실제 Anthropic LLM으로 --input 옵션만으로(--topic 없이)
dry-run을 테스트할 수 있도록, facts/sources/market_data가 모두 채워진
"테스트 전용" 샘플이다 (data/input/sample_treasury_buyback.json 의
market_data.notes 참고).

여기서는 다음 두 가지를 확인한다:
1. LLM 응답이 fixture 안의 숫자/날짜/fact id만 근거로 사용하면
   FactGroundingError/HallucinationDetectedError 없이 파이프라인이
   끝까지 실행된다 (topic도 fixture의 "topic" 필드에서 가져온다 —
   run_pipeline(topic=None, ...)).
2. fixture에 없는 숫자를 LLM이 지어내면, 이 fixture를 쓸 때도
   기존과 동일하게 HallucinationDetectedError로 차단된다 — 즉
   "환각 탐지 로직 자체를 약화하지 않았다"는 것을 증명한다.
"""
import json
import os

from tests.conftest import FakeLlmClient

from modules.wordpress_writer.generator import HallucinationDetectedError
from pipeline.orchestrator import run_pipeline

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"

# fixture(data/input/sample_treasury_buyback.json)에 실제로 존재하는 숫자/날짜만
# 사용한 정상적인 WordPressArticle 응답. fact_001~004를 모두 근거로 인용한다.
GROUNDED_ARTICLE = {
    "title": "미국 재무부 바이백 확대, 금융시장에 주는 영향",
    "slug": "us-treasury-buyback-market-impact",
    "excerpt": "재무부의 분기 국채 바이백 확대가 채권·주식 시장에 미치는 영향을 정리한다.",
    "meta_description": "미국 재무부의 국채 바이백 확대 발표가 금리와 달러, 위험자산에 미치는 영향을 분석한다.",
    "content_markdown": (
        "## 핵심 답변\n"
        "미국 재무부가 분기 국채 바이백 규모를 300억 달러로 발표하며 "
        "장기금리는 소폭 하락했고 달러 인덱스는 강보합세를 보였다.\n\n"
        "## 핵심 숫자/사실\n"
        "- 국채 바이백 규모: 300억 달러 (2026-08-27 발표)\n"
        "- 미국 10년물 국채금리: 4.05%\n"
        "- 달러 인덱스(DXY): 101.2 (0.15% 상승)\n\n"
        "## 무슨 일이 일어났나\n"
        "2026년 8월 27일 미국 재무부는 분기 국채 바이백 규모를 300억 달러로 "
        "확대 발표했다. 발표 직후 미국 10년물 국채금리는 4.05%를 기록했고, "
        "같은 날 달러 인덱스(DXY)는 101.2로 0.15% 상승했다.\n\n"
        "## 왜 중요한가\n"
        "바이백 확대는 유동성이 부족한 구간에서 재무부가 국채를 직접 매입하는 "
        "조치로, 장기금리 경로에 영향을 줄 수 있다.\n\n"
        "## 인과관계\n"
        "재무부의 바이백 확대는 유동성이 부족한 구간에서의 국채 매입을 늘려 "
        "장기금리에 하방 압력을 준 것으로 보인다.\n\n"
        "## 채권시장 영향\n"
        "장기 국채금리에 하방 압력을 준 것으로 해석된다.\n\n"
        "## 주식시장 영향\n"
        "위험자산 심리 개선 요인으로 해석될 여지가 있다.\n\n"
        "## Bull case\n"
        "- 바이백이 시장 유동성을 개선해 변동성을 낮출 수 있다.\n\n"
        "## Bear case\n"
        "- 바이백 규모가 예상보다 커지면 재정 건전성 우려가 부각될 수 있다.\n\n"
        "## 주요 리스크\n"
        "- 차기 재무부 발표에서 바이백 규모가 축소될 가능성이 있다.\n\n"
        "## thesis를 무효화할 수 있는 조건\n"
        "재무부가 바이백 규모를 공식적으로 축소 발표하는 경우 이 분석의 전제가 "
        "무효화될 수 있다.\n\n"
        "## 앞으로 확인해야 할 지표\n"
        "다음 분기 재융자 발표(QRA)와 차기 국채 바이백 운영 일정을 확인해야 한다.\n\n"
        "## 핵심 요약\n"
        "재무부의 300억 달러 바이백 발표 이후 10년물 금리는 4.05%, 달러 인덱스는 "
        "101.2를 기록했다. 일부 시장 참가자는 유동성 프리미엄 완화 효과가 있을 "
        "것으로 본다."
    ),
    "primary_keyword": "미국 재무부 바이백",
    "related_keywords": ["국채금리", "달러 인덱스"],
    "used_fact_ids": ["fact_001", "fact_002", "fact_003", "fact_004"],
}

# GROUNDED_ARTICLE과 동일하지만, fixture 어디에도 없는 숫자(650.12)를
# 지어내 넣은 응답 - 환각 탐지가 여전히 작동하는지 확인하기 위한 것이다.
HALLUCINATED_ARTICLE = {
    **GROUNDED_ARTICLE,
    "content_markdown": GROUNDED_ARTICLE["content_markdown"].replace(
        "101.2를 기록했다.",
        "101.2를 기록했고, 관련 국채 선물 가격은 650.12를 나타냈다.",
    ),
}


def test_pipeline_runs_end_to_end_with_grounded_treasury_buyback_fixture():
    """fixture 안의 숫자/날짜/fact id만 근거로 쓰면 예외 없이 끝까지 실행된다.

    topic 인자를 넘기지 않아도(topic=None) fixture 파일의 "topic" 필드로
    부터 주제가 채워진다.
    """
    fake_client = FakeLlmClient(json.dumps(GROUNDED_ARTICLE, ensure_ascii=False))

    content = run_pipeline(
        topic=None,
        market_data_path=EXTENDED_INPUT,
        llm_client=fake_client,
        publish=True,
        dry_run=True,
    )

    assert content.meta.topic == "미국 재무부 바이백이 금융시장에 미치는 영향"
    assert content.wordpress.content_html
    assert content.wordpress.fact_validation_status in ("PASS", "REVIEW_REQUIRED")
    assert content.publish.published is False

    saved_path = f"data/master/{content.meta.id}.json"
    assert os.path.exists(saved_path)
    os.remove(saved_path)


def test_pipeline_still_blocks_hallucinated_number_with_treasury_buyback_fixture():
    """fixture를 써도, fixture에 없는 숫자를 LLM이 지어내면 여전히 차단된다.

    환각 탐지 로직 자체는 이번 라운드에서 전혀 손대지 않았음을 증명하는
    회귀 테스트다.
    """
    fake_client = FakeLlmClient(json.dumps(HALLUCINATED_ARTICLE, ensure_ascii=False))

    try:
        run_pipeline(
            topic=None,
            market_data_path=EXTENDED_INPUT,
            llm_client=fake_client,
            publish=True,
            dry_run=True,
        )
        raised = False
    except HallucinationDetectedError:
        raised = True

    assert raised, "fixture에 없는 숫자(650.12)가 포함됐는데도 예외가 발생하지 않았다."
