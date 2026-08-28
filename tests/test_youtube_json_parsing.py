"""modules/youtube_meta/generator.py의 구조화 출력 파싱 안정성 회귀 테스트.

실제 --generate-all 실행에서 YouTube 채널만 다음 오류로 실패한 적이
있다:
    LLM 응답을 JSON으로 파싱하지 못했습니다: Expecting value: line 1 column 1
원인은 응답에 마크다운 코드펜스가 없고 앞에 설명 문구가 붙어 있을 때
(예: "Here's the metadata:\\n\\n{...}") 기존 파서가 raw.strip()을
그대로 json.loads에 넘겨 실패했기 때문이다. 이 파일은 그 시나리오와,
빈 응답/비정상 응답/최대 1회 schema-repair 재시도 동작을 확인한다.

Threads/NotebookLM/Thumbnail은 이번 라운드에서 건드리지 않았다 -
tests/test_channel_generators_llm.py가 그대로 커버한다.
"""
import json

import pytest

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.youtube_meta.generator import (
    YoutubeGenerationError,
    _extract_json_object,
    _response_preview,
    generate_youtube_output,
)

from .conftest import FakeLlmClient
from .test_channel_generators_llm import GOOD_YOUTUBE

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"


def _load_treasury_content():
    input_data = load_market_content_input_from_json_file(EXTENDED_INPUT)
    return build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )


GOOD_YOUTUBE_JSON = json.dumps(GOOD_YOUTUBE, ensure_ascii=False)


# ---- 1. 실제 보고된 버그: 코드펜스 없이 앞에 설명 문구가 붙은 응답 ----


def test_extract_json_object_handles_leading_prose_without_fence():
    raw = f"Here's the YouTube metadata you requested:\n\n{GOOD_YOUTUBE_JSON}"
    extracted = _extract_json_object(raw)
    assert json.loads(extracted) == GOOD_YOUTUBE


def test_generation_succeeds_when_response_has_leading_prose_without_fence():
    content = _load_treasury_content()
    raw = f"Here's the YouTube metadata you requested:\n\n{GOOD_YOUTUBE_JSON}"
    fake_client = FakeLlmClient(raw)

    result = generate_youtube_output(content, llm_client=fake_client)

    assert result.youtube.title == GOOD_YOUTUBE["recommended_title"]
    assert len(fake_client.calls) == 1  # 첫 시도에서 성공했으므로 재시도는 없어야 한다.


# ---- 2. 앞뒤 모두 설명 문구가 붙은 경우 ----


def test_generation_succeeds_when_response_has_leading_and_trailing_prose():
    content = _load_treasury_content()
    raw = f"Sure, here it is:\n\n{GOOD_YOUTUBE_JSON}\n\nLet me know if you need any changes!"
    fake_client = FakeLlmClient(raw)

    result = generate_youtube_output(content, llm_client=fake_client)

    assert result.youtube.title == GOOD_YOUTUBE["recommended_title"]


# ---- 3. 코드펜스 제거 후 파싱(json 태그/일반 펜스 모두) ----


def test_generation_succeeds_with_json_tagged_code_fence():
    content = _load_treasury_content()
    raw = f"```json\n{GOOD_YOUTUBE_JSON}\n```"
    fake_client = FakeLlmClient(raw)

    result = generate_youtube_output(content, llm_client=fake_client)

    assert result.youtube.title == GOOD_YOUTUBE["recommended_title"]


def test_generation_succeeds_with_plain_code_fence():
    content = _load_treasury_content()
    raw = f"```\n{GOOD_YOUTUBE_JSON}\n```"
    fake_client = FakeLlmClient(raw)

    result = generate_youtube_output(content, llm_client=fake_client)

    assert result.youtube.title == GOOD_YOUTUBE["recommended_title"]


def test_generation_succeeds_with_prose_before_fenced_json():
    content = _load_treasury_content()
    raw = f"Here you go:\n```json\n{GOOD_YOUTUBE_JSON}\n```\nHope that helps."
    fake_client = FakeLlmClient(raw)

    result = generate_youtube_output(content, llm_client=fake_client)

    assert result.youtube.title == GOOD_YOUTUBE["recommended_title"]


# ---- 4. 빈 응답/비정상 응답은 명확한 에러 ----


def test_extract_json_object_raises_clear_error_on_empty_response():
    with pytest.raises(YoutubeGenerationError, match="비어 있습니다"):
        _extract_json_object("")


def test_extract_json_object_raises_clear_error_when_no_braces_found():
    with pytest.raises(YoutubeGenerationError, match="JSON 객체를 찾지 못했습니다"):
        _extract_json_object("죄송합니다, 요청을 처리할 수 없습니다.")


def test_generation_fails_clearly_on_repeated_empty_response():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(responses=["", ""])

    with pytest.raises(YoutubeGenerationError):
        generate_youtube_output(content, llm_client=fake_client)


# ---- 5. 최대 1회 schema-repair 재시도(무한 재시도 아님) ----


def test_repair_retry_succeeds_on_second_attempt():
    """첫 응답은 펜스도 없고 중괄호도 없는 완전히 깨진 응답, 두 번째
    (repair) 응답은 정상 JSON - 재시도로 복구되어야 한다.
    """
    content = _load_treasury_content()
    broken = "죄송하지만 요청을 이해하지 못했습니다."
    fake_client = FakeLlmClient(responses=[broken, GOOD_YOUTUBE_JSON])

    result = generate_youtube_output(content, llm_client=fake_client)

    assert result.youtube.title == GOOD_YOUTUBE["recommended_title"]
    assert len(fake_client.calls) == 2  # 원 시도 1회 + repair 1회, 총 2회만 호출되어야 한다.


def test_repair_retry_uses_stricter_repair_system_prompt():
    content = _load_treasury_content()
    broken = "죄송하지만 요청을 이해하지 못했습니다."
    fake_client = FakeLlmClient(responses=[broken, GOOD_YOUTUBE_JSON])

    generate_youtube_output(content, llm_client=fake_client)

    assert len(fake_client.calls) == 2
    first_system_prompt = fake_client.calls[0]["system_prompt"]
    second_system_prompt = fake_client.calls[1]["system_prompt"]
    assert first_system_prompt != second_system_prompt
    assert "이전 응답을 설명하거나 사과하지 않는다" in second_system_prompt


def test_repair_retry_does_not_loop_forever_when_both_attempts_fail():
    """두 번째(repair) 시도도 실패하면 세 번째 시도 없이 바로 에러를
    내야 한다 - 무한 재시도 금지.
    """
    content = _load_treasury_content()
    fake_client = FakeLlmClient(responses=["broken response 1", "broken response 2"])

    with pytest.raises(YoutubeGenerationError):
        generate_youtube_output(content, llm_client=fake_client)

    assert len(fake_client.calls) == 2  # 정확히 2회만 호출되고 멈춰야 한다.


def test_usage_log_records_both_attempts_on_repair():
    content = _load_treasury_content()
    broken = "죄송하지만 요청을 이해하지 못했습니다."
    fake_client = FakeLlmClient(responses=[broken, GOOD_YOUTUBE_JSON])
    usage_log: list[dict] = []

    generate_youtube_output(content, llm_client=fake_client, usage_log=usage_log)

    assert len(usage_log) == 2
    assert [record["attempt"] for record in usage_log] == [1, 2]
    assert all(record["channel"] == "youtube" for record in usage_log)


# ---- 6. 안전한 preview(전체 raw response를 노출하지 않음) ----


def test_response_preview_truncates_long_text():
    long_text = "가" * 500
    preview = _response_preview(long_text)

    assert len(preview) < len(long_text)
    assert preview.endswith("...")


def test_error_message_does_not_leak_full_long_raw_response():
    content = _load_treasury_content()
    long_broken_response = "이것은 매우 긴 오류 응답입니다. " * 200
    fake_client = FakeLlmClient(responses=[long_broken_response, long_broken_response])

    with pytest.raises(YoutubeGenerationError) as exc_info:
        generate_youtube_output(content, llm_client=fake_client)

    # 에러 메시지 안에 원본 응답 전체가 그대로 들어있으면 안 된다(미리보기만 포함).
    message = str(exc_info.value)
    assert long_broken_response not in message
    assert len(message) < len(long_broken_response)
