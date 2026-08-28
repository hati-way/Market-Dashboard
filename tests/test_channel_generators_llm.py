"""신규 다채널 생성기(threads_writer/notebooklm_script/youtube_meta/
thumbnail_prompt의 *_output 함수)에 대한 회귀 테스트.

기존 placeholder 함수(generate_threads_content 등, pipeline/orchestrator.py
가 계속 쓴다)는 이 라운드에서 건드리지 않았다 - tests/test_channel_
generators.py가 그대로 커버한다. 이 파일은 신규 real-LLM 함수만
다룬다. 실제 Anthropic API는 호출하지 않는다(FakeLlmClient).
"""
import json

import pytest
from pydantic import ValidationError

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.notebooklm_script.generator import (
    NotebookLmFactGroundingError,
    NotebookLmGenerationError,
    generate_notebooklm_output,
)
from modules.notebooklm_script.models import NotebookLmScriptOutput
from modules.thumbnail_prompt.generator import (
    ThumbnailFactGroundingError,
    ThumbnailGenerationError,
    generate_thumbnail_output,
)
from modules.thumbnail_prompt.models import ThumbnailOutput
from modules.threads_writer.generator import (
    ThreadsFactGroundingError,
    ThreadsGenerationError,
    generate_threads_output,
)
from modules.threads_writer.models import ThreadsOutput
from modules.youtube_meta.generator import YoutubeFactGroundingError, generate_youtube_output
from modules.youtube_meta.models import YouTubeOutput

from .conftest import FakeLlmClient

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"


def _load_treasury_content():
    input_data = load_market_content_input_from_json_file(EXTENDED_INPUT)
    return build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )


# fixture 안의 값만 근거로 쓰는 정상적인 채널별 응답.
GOOD_THREADS = {
    "posts": [
        "1/4 미국 재무부가 국채를 다시 사들이기 시작했다. 규모는 300억 달러. 왜 하필 지금, 이만큼일까.",
        "2/4 이번 바이백은 유동성이 얇은 만기 구간을 겨냥했다. 바이백 확대 → 유동성 개선 → 금리 변동성 완화. 중요한 건 어느 구간을 지원하느냐다.",
        "3/4 발표 직후 10년물 금리는 4.05%로 내렸다. 그래서 위험자산엔 우호적인 신호로 읽힌다. 일부 시장 참여자는 장기물 발행 부담도 줄어들 수 있다고 본다.",
        "4/4 앞으로 볼 건 다음 QRA와 차기 바이백 운영 일정이다. 결론: 숫자보다 재무부가 어느 구간을 지원하는지가 핵심이다.",
    ],
    "hook": "미국이 국채를 다시 사들이는 규모를 키웠다. 300억 달러, 왜 하필 지금일까.",
    "key_message": "바이백은 규모보다 어느 구간을 지원하느냐가 중요하다.",
    "used_fact_ids": ["fact_001", "fact_002", "fact_004"],
}

GOOD_NOTEBOOKLM = {
    "title": "미국 국채 바이백 300억 달러, 시장에 어떤 의미일까",
    "hook": "미국 재무부가 국채를 300억 달러어치 다시 사들였습니다. 그런데 금리는 오히려 내려갔습니다. 왜 그랬을까요?",
    "script": (
        "미국 재무부가 국채를 300억 달러어치 다시 사들였습니다. 그런데 금리는 오히려 내려갔습니다. 왜 그랬을까요?\n\n"
        "재무부는 2026년 8월 27일, 분기 국채 바이백 규모를 300억 달러로 발표했습니다. "
        "발표 직후 미국 10년물 국채금리는 4.05%로 내려갔습니다. 달러 인덱스는 101.2로 소폭 올랐습니다.\n\n"
        "정부가 예전에 판 채권을 시장에서 다시 사들이는 겁니다. 이걸 바이백이라고 부릅니다. "
        "시중에 풀린 채권 물량을 줄이는 효과가 있습니다.\n\n"
        "유동성이 부족한 구간을 재무부가 직접 사들이면 어떻게 될까요. 그 구간의 가격 변동성이 줄어들 수 있습니다. "
        "여기서 중요한 건 규모보다 어느 구간을 지원하느냐입니다.\n\n"
        "채권시장에서는 장기금리에 하방 압력이 실릴 수 있다는 해석이 나옵니다. "
        "유동성이 개선되면 딜러들의 재고 부담도 줄어들 수 있습니다.\n\n"
        "금리가 낮아지면 주식시장에도 간접적으로 영향을 줍니다. 할인율 부담이 줄어드는 경로입니다.\n\n"
        "그런데 다음 분기 바이백 규모가 줄어들면 얘기가 달라집니다. 이 흐름은 다시 뒤집힐 수 있습니다.\n\n"
        "앞으로는 다음 분기 재융자 발표, QRA를 지켜봐야 합니다. 바이백 규모가 더 커지면 지금 설명한 해석에 힘이 실립니다. "
        "반대로 규모가 줄어들면 오늘 얘기한 흐름은 다시 봐야 합니다. "
        "한 가지 해석은, 이번 조치가 장기물 발행 부담을 완화할 수 있다는 겁니다. "
        "다만 일부 시장에서는 이 해석에 신중한 입장을 보입니다.\n\n"
        "결국 확인해야 할 건 재무부가 다음에도 같은 구간을 지원하느냐입니다. "
        "그 답에 따라 오늘 설명한 흐름이 이어질지, 아니면 다시 봐야 할지가 갈립니다."
    ),
    "chapters": [
        "Hook", "사건 설명", "바이백 개념 설명", "전달 경로", "채권시장",
        "주식시장", "반대 시나리오", "앞으로 볼 지표", "결론",
    ],
    "used_fact_ids": ["fact_001", "fact_002", "fact_003", "fact_004"],
}

GOOD_YOUTUBE = {
    "title_candidates": [
        "미국이 국채를 다시 사들이는 이유, 300억 달러 바이백의 진짜 의미",
        "미국 국채 바이백 300억 달러, 금리에 어떤 신호일까",
        "재무부의 300억 달러 바이백, 시장이 주목하는 이유",
        "국채 바이백 확대, 다음 분기 금리를 좌우할까",
        "300억 달러 바이백이 알려주는 채권시장의 신호",
    ],
    "recommended_title": "미국이 국채를 다시 사들이는 이유, 300억 달러 바이백의 진짜 의미",
    "description": (
        "미국 재무부가 분기 국채 바이백 규모를 300억 달러로 확대했습니다.\n"
        "이 영상은 바이백이 왜 중요한지, 금리와 달러에 어떤 영향을 주는지 설명합니다.\n"
        "- 2026년 8월 27일 300억 달러 바이백 발표\n"
        "- 10년물 국채금리 4.05%\n"
        "출처: U.S. Department of the Treasury\n"
        "본 영상은 투자 권유가 아닙니다."
    ),
    "tags": ["미국국채", "바이백", "국채금리", "재무부", "거시경제"],
    "pinned_comment": "오늘의 핵심: 300억 달러 바이백, 10년물 금리 4.05%",
    "used_fact_ids": ["fact_001", "fact_002"],
}

GOOD_THUMBNAIL = {
    "thumbnail_text_candidates": [
        "미국은 왜 국채를 다시 살까",
        "300억 달러의 신호",
        "바이백이 던진 질문",
        "다시 사들이는 이유",
        "금리는 어디로",
    ],
    "recommended_text": "300억 달러의 신호",
    "midjourney_prompt": (
        "editorial illustration symbolizing government bond buyback, "
        "abstract flow of currency and bonds, dark blue and neon accent colors, "
        "high contrast composition, subject fills the frame, no text, no typography, "
        "16:9 --ar 16:9"
    ),
    "visual_concept": "국채가 다시 흡수되는 흐름을 상징적으로 보여준다",
    "avoid_elements": ["실존 정치인 얼굴", "과도한 텍스트", "전형적인 주식 차트 클리셰"],
    "used_fact_ids": ["fact_001"],
}


# ---- 2. Threads 3~5 posts validation ----


def test_threads_output_requires_3_to_5_posts():
    with pytest.raises(ValidationError):
        ThreadsOutput.model_validate({**GOOD_THREADS, "posts": ["only one post"]})

    with pytest.raises(ValidationError):
        ThreadsOutput.model_validate({**GOOD_THREADS, "posts": [f"post {i}" for i in range(6)]})

    ok = ThreadsOutput.model_validate(GOOD_THREADS)
    assert 3 <= len(ok.posts) <= 5


def test_threads_output_generation_end_to_end():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))

    result = generate_threads_output(content, llm_client=fake_client)

    assert 3 <= len(result.threads.posts) <= 5
    assert result.threads.hook
    assert result.threads.fact_validation_status in ("PASS", "REVIEW_REQUIRED")


# ---- 3. Threads 평어 스타일 기본 검증(금지 표현이 시스템 프롬프트에 명시돼 있는지) ----


def test_threads_system_prompt_bans_ai_report_phrases():
    from modules.threads_writer.generator import _SYSTEM_PROMPT

    for banned in ("제공된 자료에 따르면", "본 분석에서는", "결론적으로"):
        assert banned in _SYSTEM_PROMPT  # 금지 목록 안에 명시되어 있어야 한다
    assert "이모지" in _SYSTEM_PROMPT


def test_threads_generated_posts_do_not_contain_banned_phrases():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))

    result = generate_threads_output(content, llm_client=fake_client)
    combined = "\n".join(p.text for p in result.threads.posts)

    for banned in ("제공된 자료에 따르면", "본 분석에서는", "결론적으로"):
        assert banned not in combined


# ---- 4. NotebookLM 필수 구조 검증 ----


def test_notebooklm_output_requires_nonempty_script_and_chapters():
    with pytest.raises(ValidationError):
        NotebookLmScriptOutput.model_validate({**GOOD_NOTEBOOKLM, "script": "   "})
    with pytest.raises(ValidationError):
        NotebookLmScriptOutput.model_validate({**GOOD_NOTEBOOKLM, "chapters": []})


def test_notebooklm_output_generation_end_to_end():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_NOTEBOOKLM, ensure_ascii=False))

    result = generate_notebooklm_output(content, llm_client=fake_client)

    assert result.notebooklm.script
    assert result.notebooklm.chapters
    assert result.notebooklm.fact_validation_status in ("PASS", "REVIEW_REQUIRED")


# ---- 5. YouTube title 후보 5개 ----


def test_youtube_output_requires_exactly_5_title_candidates():
    with pytest.raises(ValidationError):
        YouTubeOutput.model_validate(
            {**GOOD_YOUTUBE, "title_candidates": GOOD_YOUTUBE["title_candidates"][:3]}
        )

    ok = YouTubeOutput.model_validate(GOOD_YOUTUBE)
    assert len(ok.title_candidates) == 5


def test_youtube_output_generation_end_to_end():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_YOUTUBE, ensure_ascii=False))

    result = generate_youtube_output(content, llm_client=fake_client)

    assert len(result.youtube.title_candidates) == 5
    assert result.youtube.title == GOOD_YOUTUBE["recommended_title"]
    assert result.youtube.fact_validation_status in ("PASS", "REVIEW_REQUIRED")


# ---- 6. Thumbnail 문구 후보 5개 ----


def test_thumbnail_output_requires_exactly_5_text_candidates():
    with pytest.raises(ValidationError):
        ThumbnailOutput.model_validate(
            {**GOOD_THUMBNAIL, "thumbnail_text_candidates": GOOD_THUMBNAIL["thumbnail_text_candidates"][:2]}
        )

    ok = ThumbnailOutput.model_validate(GOOD_THUMBNAIL)
    assert len(ok.thumbnail_text_candidates) == 5


def test_thumbnail_output_generation_end_to_end():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_THUMBNAIL, ensure_ascii=False))

    result = generate_thumbnail_output(content, llm_client=fake_client)

    assert len(result.thumbnail.thumbnail_text_candidates) == 5
    assert result.thumbnail.canva_text == GOOD_THUMBNAIL["recommended_text"]
    assert result.thumbnail.fact_validation_status in ("PASS", "REVIEW_REQUIRED")


# ---- 7. 존재하지 않는 fact id -> channel FAIL ----


def test_threads_fails_on_nonexistent_fact_id():
    content = _load_treasury_content()
    bad = {**GOOD_THREADS, "used_fact_ids": ["fact_999"]}
    fake_client = FakeLlmClient(json.dumps(bad, ensure_ascii=False))

    with pytest.raises(ThreadsFactGroundingError):
        generate_threads_output(content, llm_client=fake_client)


def test_youtube_fails_on_nonexistent_fact_id():
    content = _load_treasury_content()
    bad = {**GOOD_YOUTUBE, "used_fact_ids": ["fact_999"]}
    fake_client = FakeLlmClient(json.dumps(bad, ensure_ascii=False))

    with pytest.raises(YoutubeFactGroundingError):
        generate_youtube_output(content, llm_client=fake_client)


# ---- 8. 근거 없는 숫자 -> FAIL ----


def test_threads_fails_on_hallucinated_number():
    content = _load_treasury_content()
    hallucinated = {
        **GOOD_THREADS,
        "posts": [*GOOD_THREADS["posts"][:-1], "4/4 관련 국채 선물 가격은 650.12를 나타냈다."],
    }
    fake_client = FakeLlmClient(json.dumps(hallucinated, ensure_ascii=False))

    with pytest.raises(ThreadsGenerationError):
        generate_threads_output(content, llm_client=fake_client)


def test_notebooklm_fails_on_hallucinated_number():
    content = _load_treasury_content()
    hallucinated = {**GOOD_NOTEBOOKLM, "script": GOOD_NOTEBOOKLM["script"] + " 국채 선물 가격은 650.12였습니다."}
    fake_client = FakeLlmClient(json.dumps(hallucinated, ensure_ascii=False))

    with pytest.raises(NotebookLmGenerationError):
        generate_notebooklm_output(content, llm_client=fake_client)


def test_thumbnail_fails_on_hallucinated_number_in_text():
    content = _load_treasury_content()
    hallucinated = {**GOOD_THUMBNAIL, "recommended_text": "650.12의 신호"}
    fake_client = FakeLlmClient(json.dumps(hallucinated, ensure_ascii=False))

    with pytest.raises(ThumbnailGenerationError):
        generate_thumbnail_output(content, llm_client=fake_client)


# ---- 9. low confidence fact 사용 -> REVIEW_REQUIRED(FAIL 아님) ----


def test_notebooklm_review_required_when_low_confidence_fact_used():
    content = _load_treasury_content()
    with_low_confidence = {
        **GOOD_NOTEBOOKLM,
        "script": GOOD_NOTEBOOKLM["script"]
        + " 일부 시장 참여자는 이번 조치가 장기물 발행 부담을 완화할 가능성이 있다고 봅니다.",
        "used_fact_ids": [*GOOD_NOTEBOOKLM["used_fact_ids"], "fact_004"],
    }
    fake_client = FakeLlmClient(json.dumps(with_low_confidence, ensure_ascii=False))

    result = generate_notebooklm_output(content, llm_client=fake_client)

    assert result.notebooklm.fact_validation_status == "REVIEW_REQUIRED"
    assert any("confidence=low" in w for w in result.notebooklm.fact_validation_warnings)


def test_thumbnail_fact_grounding_error_carries_result():
    content = _load_treasury_content()
    bad = {**GOOD_THUMBNAIL, "used_fact_ids": ["fact_999"]}
    fake_client = FakeLlmClient(json.dumps(bad, ensure_ascii=False))

    with pytest.raises(ThumbnailFactGroundingError) as exc_info:
        generate_thumbnail_output(content, llm_client=fake_client)
    assert "fact_999" in exc_info.value.result.invalid_fact_ids
