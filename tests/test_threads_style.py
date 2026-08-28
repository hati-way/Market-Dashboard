"""Threads 채널 문체 강화 회귀 테스트.

돈맥 Threads 전용 문체(번호 매김, 짧은 hook, 인과관계 화살표, 자연스러운
연결어, 내부 fact id 비노출)를 강제하는 부분을 확인한다. NotebookLM/
YouTube/Thumbnail은 이번 라운드에서 건드리지 않았다.
"""
import json
import re

import pytest
from pydantic import ValidationError

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.threads_writer.generator import (
    DEFAULT_MAX_TOKENS,
    ThreadsGenerationError,
    ThreadsInternalIdLeakError,
    _check_no_internal_ids_leaked,
    _SYSTEM_PROMPT,
    generate_threads_output,
)
from modules.threads_writer.models import DEFAULT_POST_COUNT, MAX_POSTS, MIN_POSTS, ThreadsOutput

from .conftest import FakeLlmClient
from .test_channel_generators_llm import GOOD_THREADS

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"


def _load_treasury_content():
    input_data = load_market_content_input_from_json_file(EXTENDED_INPUT)
    return build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )


# ---- 1. 각 post는 "N/전체 " 번호로 시작해야 한다 ----


def test_good_fixture_posts_are_numbered_correctly():
    output = ThreadsOutput.model_validate(GOOD_THREADS)
    total = len(output.posts)
    for i, post in enumerate(output.posts, start=1):
        assert post.startswith(f"{i}/{total} ")


def test_missing_post_number_prefix_is_rejected():
    bad_posts = list(GOOD_THREADS["posts"])
    bad_posts[0] = bad_posts[0].split(" ", 1)[1]  # "1/4 " 접두어 제거
    with pytest.raises(ValidationError, match="1/4"):
        ThreadsOutput.model_validate({**GOOD_THREADS, "posts": bad_posts})


def test_mismatched_post_number_is_rejected():
    """전체 개수와 번호가 어긋나면(예: 4개 중 3번째가 "5/4") 거부한다."""
    bad_posts = list(GOOD_THREADS["posts"])
    bad_posts[2] = "5/4 " + bad_posts[2].split(" ", 1)[1]
    with pytest.raises(ValidationError):
        ThreadsOutput.model_validate({**GOOD_THREADS, "posts": bad_posts})


def test_post_number_must_match_actual_total_not_just_any_fraction():
    """번호는 실제 posts 개수와 일치해야 한다 - "1/5"처럼 있어 보이는
    형식이어도 실제 총 개수(4)와 다르면 거부한다.
    """
    bad_posts = [f"1/5 {p.split(' ', 1)[1]}" if i == 0 else p for i, p in enumerate(GOOD_THREADS["posts"])]
    with pytest.raises(ValidationError):
        ThreadsOutput.model_validate({**GOOD_THREADS, "posts": bad_posts})


# ---- 2. 첫 post(hook)는 2~4개의 짧은 문장 ----


def test_good_fixture_hook_post_has_two_to_four_short_sentences():
    output = ThreadsOutput.model_validate(GOOD_THREADS)
    hook_post = output.posts[0]
    # 번호 접두어를 뗀 본문만 문장 수를 센다.
    body = hook_post.split(" ", 1)[1]
    sentence_count = len([s for s in re.split(r"[.?!]\s*", body) if s.strip()])
    assert 2 <= sentence_count <= 4


# ---- 3~4. 기본 4개, 3~5개까지만 허용(기존 범위 유지) ----


def test_default_post_count_constant_is_four():
    assert DEFAULT_POST_COUNT == 4
    assert MIN_POSTS == 3
    assert MAX_POSTS == 5


def test_system_prompt_states_default_four_posts():
    assert "기본 4개" in _SYSTEM_PROMPT


# ---- 5. 인과관계 화살표(→) / 자연스러운 연결어 지침이 프롬프트에 있는지 ----


def test_system_prompt_encourages_arrow_and_natural_connectors():
    assert "→" in _SYSTEM_PROMPT
    for connector in ("중요한 건", "그런데", "그래서", "앞으로 볼 건"):
        assert connector in _SYSTEM_PROMPT


def test_good_fixture_uses_arrow_for_causal_flow():
    assert any("→" in post for post in GOOD_THREADS["posts"])


# ---- 6. 기사체/리포트체 금지 문구가 프롬프트에 명시돼 있는지 ----


def test_system_prompt_bans_report_style_endings():
    for banned in ("~로 나타났다", "~라고 밝혔다", "~을 시사한다"):
        assert banned in _SYSTEM_PROMPT


def test_good_fixture_avoids_report_style_endings():
    combined = " ".join(GOOD_THREADS["posts"])
    for banned in ("것으로 나타났다", "라고 밝혔다", "것으로 보인다"):
        assert banned not in combined


# ---- 7. 마지막 post는 지표 + 한 줄 결론 ----


def test_good_fixture_last_post_has_indicator_and_conclusion():
    last_post = GOOD_THREADS["posts"][-1]
    assert "결론" in last_post or "핵심" in last_post


# ---- 8. 내부 fact id는 사용자 노출 금지 ----


def test_internal_id_leak_detected_in_post():
    output = ThreadsOutput.model_validate(
        {**GOOD_THREADS, "posts": [*GOOD_THREADS["posts"][:-1], "4/4 핵심 근거는 fact_001, fact_002다."]}
    )
    with pytest.raises(ThreadsInternalIdLeakError, match=r"posts\[3\]"):
        _check_no_internal_ids_leaked(output)


def test_internal_id_leak_detected_in_hook_or_key_message():
    output = ThreadsOutput.model_validate({**GOOD_THREADS, "key_message": "근거: fact_004"})
    with pytest.raises(ThreadsInternalIdLeakError, match="key_message"):
        _check_no_internal_ids_leaked(output)


def test_clean_fixture_does_not_trigger_leak_error():
    output = ThreadsOutput.model_validate(GOOD_THREADS)
    _check_no_internal_ids_leaked(output)  # 예외가 나지 않아야 한다.


def test_generation_fails_when_post_leaks_internal_fact_id():
    content = _load_treasury_content()
    leaking = {
        **GOOD_THREADS,
        "posts": [*GOOD_THREADS["posts"][:-1], "4/4 핵심 근거는 fact_001, fact_002다."],
    }
    fake_client = FakeLlmClient(json.dumps(leaking, ensure_ascii=False))

    with pytest.raises(ThreadsInternalIdLeakError):
        generate_threads_output(content, llm_client=fake_client)


# ---- low confidence fact는 제한적 표현으로만(내부 id 비노출과 함께) ----


def test_low_confidence_fact_uses_limited_natural_language_without_leaking_id():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))

    result = generate_threads_output(content, llm_client=fake_client)
    combined = "\n".join(p.text for p in result.threads.posts)

    assert "일부 시장 참여자는" in combined
    assert "fact_" not in combined.lower()
    assert result.threads.fact_validation_status == "REVIEW_REQUIRED"
    assert any("confidence=low" in w for w in result.threads.fact_validation_warnings)


# ---- 9. 기존 Fact Grounding 유지 확인 ----


def test_fact_grounding_still_blocks_nonexistent_fact_id_and_hallucination():
    content = _load_treasury_content()

    bad = {**GOOD_THREADS, "used_fact_ids": ["fact_999"]}
    with pytest.raises(ThreadsGenerationError):
        generate_threads_output(content, llm_client=FakeLlmClient(json.dumps(bad, ensure_ascii=False)))

    hallucinated = {
        **GOOD_THREADS,
        "posts": [*GOOD_THREADS["posts"][:-1], "4/4 관련 국채 선물 가격은 650.12를 나타냈다."],
    }
    with pytest.raises(ThreadsGenerationError):
        generate_threads_output(
            content, llm_client=FakeLlmClient(json.dumps(hallucinated, ensure_ascii=False))
        )


def test_generation_succeeds_end_to_end_with_new_style_fixture():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))

    result = generate_threads_output(content, llm_client=fake_client)

    assert MIN_POSTS <= len(result.threads.posts) <= MAX_POSTS
    assert result.threads.posts[0].text.startswith("1/")
    assert result.threads.fact_validation_status in ("PASS", "REVIEW_REQUIRED")


def test_max_tokens_unchanged_constant_still_exported():
    # 이번 라운드는 프롬프트/검증만 바꿨다 - 토큰 상한 등 기존 설정은 그대로다.
    assert DEFAULT_MAX_TOKENS == 2048
