"""NotebookLM 채널 영상 내레이션 문체 강화 회귀 테스트.

구조(9구간)와 Fact Grounding은 그대로 두고 문체만 개선했다. Threads/
YouTube/Thumbnail은 이번 라운드에서 건드리지 않았다.
"""
import json

import pytest

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.notebooklm_script.generator import (
    _SYSTEM_PROMPT,
    NotebookLmGenerationError,
    NotebookLmInternalIdLeakError,
    _check_no_internal_ids_leaked,
    generate_notebooklm_output,
)
from modules.notebooklm_script.models import NotebookLmScriptOutput

from .conftest import FakeLlmClient
from .test_channel_generators_llm import GOOD_NOTEBOOKLM

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"


def _load_treasury_content():
    input_data = load_market_content_input_from_json_file(EXTENDED_INPUT)
    return build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )


# ---- 1~2. 짧은 문장 / 긴 문단 지양 ----


def test_system_prompt_requires_short_one_idea_sentences():
    assert "한 문장에는 원칙적으로 하나의 정보만 담는다" in _SYSTEM_PROMPT


def test_system_prompt_requires_paragraph_breaks_for_natural_pauses():
    assert "숨을 쉴 수 있도록" in _SYSTEM_PROMPT


def test_good_fixture_script_breaks_into_short_paragraphs():
    paragraphs = [p for p in GOOD_NOTEBOOKLM["script"].split("\n\n") if p.strip()]
    assert len(paragraphs) >= 5  # 긴 문단 하나로 뭉쳐 있지 않아야 한다.
    for paragraph in paragraphs:
        sentence_count = paragraph.count(".") + paragraph.count("?")
        assert sentence_count <= 5  # "두세 문장마다 줄바꿈"은 목표치이지 절대 규칙은 아니다.


# ---- 3~4. Hook 구조(핵심 숫자/사건 -> 의외의 반응 -> 질문), 20~30초 ----


def test_system_prompt_specifies_hook_structure():
    assert "핵심 숫자/사건 → 의외의 시장 반응 → 질문" in _SYSTEM_PROMPT
    assert "20~30초" in _SYSTEM_PROMPT


def test_good_fixture_hook_follows_number_reaction_question_structure():
    hook = GOOD_NOTEBOOKLM["hook"]
    assert "300억 달러" in hook  # 핵심 숫자/사건
    assert "그런데" in hook  # 의외의 반응으로 전환
    assert hook.rstrip().endswith("?") or hook.rstrip().endswith("요?")  # 질문으로 마무리


# ---- 5. 어려운 개념: 현상/비유 -> 용어 순서 ----


def test_system_prompt_requires_phenomenon_before_term():
    assert "쉬운 현상이나 비유로 먼저 설명한" in _SYSTEM_PROMPT
    assert "바이백이란 재무부가 시중의 국채를 다시 사들이는 정책입니다" in _SYSTEM_PROMPT  # 나쁜 예


def test_good_fixture_explains_buyback_concept_before_naming_it():
    script = GOOD_NOTEBOOKLM["script"]
    concept_idx = script.find("정부가 예전에 판 채권을 시장에서 다시 사들이는")
    term_idx = script.find("바이백이라고 부릅니다")
    assert concept_idx != -1 and term_idx != -1
    assert concept_idx < term_idx  # 현상 설명이 용어보다 먼저 나와야 한다.


# ---- 6. 연결어 반복 금지 ----


def test_system_prompt_forbids_repeating_the_same_connector():
    assert "같은 표현을 반복하지 않는다" in _SYSTEM_PROMPT


# ---- 7. 보고서체 금지 ----


def test_system_prompt_bans_report_style_endings():
    for banned in ("~로 나타났다", "~라고 밝혔다", "~을 시사한다"):
        assert banned in _SYSTEM_PROMPT


def test_good_fixture_avoids_report_style_endings():
    script = GOOD_NOTEBOOKLM["script"]
    for banned in ("것으로 나타났다", "라고 밝혔다", "것으로 보인다", "시사합니다"):
        assert banned not in script


# ---- 8. 저확신도 표현 ----


def test_system_prompt_requires_limited_low_confidence_phrasing():
    assert "일부 시장에서는 ~라고 봅니다" in _SYSTEM_PROMPT
    assert "한 가지 해석은 ~입니다" in _SYSTEM_PROMPT


def test_good_fixture_uses_limited_phrasing_for_low_confidence_claim():
    script = GOOD_NOTEBOOKLM["script"]
    assert "일부 시장에서는" in script or "한 가지 해석은" in script


def test_generation_result_keeps_low_confidence_hedged_without_leaking_id():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_NOTEBOOKLM, ensure_ascii=False))

    result = generate_notebooklm_output(content, llm_client=fake_client)

    assert "일부 시장에서는" in result.notebooklm.script or "한 가지 해석은" in result.notebooklm.script
    assert "fact_" not in result.notebooklm.script.lower()
    assert result.notebooklm.fact_validation_status == "REVIEW_REQUIRED"
    assert any("confidence=low" in w for w in result.notebooklm.fact_validation_warnings)


# ---- 9~10. 결론(확인 지표 중심), 마지막 30초 방향별 해석 ----


def test_system_prompt_conclusion_focuses_on_what_to_check_next():
    assert '"그래서 앞으로 무엇을 확인해야 하는가"' in _SYSTEM_PROMPT


def test_system_prompt_requires_direction_based_interpretation_in_last_30_seconds():
    assert "마지막 30초" in _SYSTEM_PROMPT
    assert "강화되는지" in _SYSTEM_PROMPT
    assert "약화되는지" in _SYSTEM_PROMPT


def test_good_fixture_explains_indicator_direction_effect():
    script = GOOD_NOTEBOOKLM["script"]
    assert "QRA" in script
    assert "힘이 실립니다" in script  # 강화되는 방향
    assert "다시 봐야 합니다" in script  # 약화되는 방향


def test_good_fixture_conclusion_is_not_a_plain_summary():
    script = GOOD_NOTEBOOKLM["script"]
    conclusion = script.split("\n\n")[-1]
    assert "확인해야 할 건" in conclusion


# ---- 11. 내부 fact id 노출 금지 ----


def test_internal_id_leak_detected_in_script():
    output = NotebookLmScriptOutput.model_validate(
        {**GOOD_NOTEBOOKLM, "script": GOOD_NOTEBOOKLM["script"] + " (근거: fact_001, fact_002)"}
    )
    with pytest.raises(NotebookLmInternalIdLeakError, match="script"):
        _check_no_internal_ids_leaked(output)


def test_internal_id_leak_detected_in_title_or_hook():
    output = NotebookLmScriptOutput.model_validate({**GOOD_NOTEBOOKLM, "hook": "핵심 근거: fact_004"})
    with pytest.raises(NotebookLmInternalIdLeakError, match="hook"):
        _check_no_internal_ids_leaked(output)


def test_clean_fixture_does_not_trigger_leak_error():
    output = NotebookLmScriptOutput.model_validate(GOOD_NOTEBOOKLM)
    _check_no_internal_ids_leaked(output)  # 예외가 나지 않아야 한다.


def test_generation_fails_when_script_leaks_internal_fact_id():
    content = _load_treasury_content()
    leaking = {**GOOD_NOTEBOOKLM, "script": GOOD_NOTEBOOKLM["script"] + " (fact_001 참고)"}
    fake_client = FakeLlmClient(json.dumps(leaking, ensure_ascii=False))

    with pytest.raises(NotebookLmInternalIdLeakError):
        generate_notebooklm_output(content, llm_client=fake_client)


# ---- 12. 기존 Fact Grounding 유지 확인 ----


def test_fact_grounding_still_blocks_nonexistent_fact_id_and_hallucination():
    content = _load_treasury_content()

    bad = {**GOOD_NOTEBOOKLM, "used_fact_ids": ["fact_999"]}
    with pytest.raises(NotebookLmGenerationError):
        generate_notebooklm_output(content, llm_client=FakeLlmClient(json.dumps(bad, ensure_ascii=False)))

    hallucinated = {**GOOD_NOTEBOOKLM, "script": GOOD_NOTEBOOKLM["script"] + " 관련 수치는 650.12였습니다."}
    with pytest.raises(NotebookLmGenerationError):
        generate_notebooklm_output(
            content, llm_client=FakeLlmClient(json.dumps(hallucinated, ensure_ascii=False))
        )


def test_generation_succeeds_end_to_end_with_new_style_fixture():
    content = _load_treasury_content()
    fake_client = FakeLlmClient(json.dumps(GOOD_NOTEBOOKLM, ensure_ascii=False))

    result = generate_notebooklm_output(content, llm_client=fake_client)

    assert result.notebooklm.script
    assert result.notebooklm.chapters
    assert result.notebooklm.fact_validation_status in ("PASS", "REVIEW_REQUIRED")


# ---- 분량: 4~6분 우선 목표, 정보 부족 시 억지로 7분 채우지 않음 ----


def test_system_prompt_targets_four_to_six_minutes_without_forcing_length():
    assert "4~6분" in _SYSTEM_PROMPT
    assert "억지로 7분을 채우지 않는다" in _SYSTEM_PROMPT


def test_good_fixture_length_is_within_four_to_six_minute_target():
    # 이 파일의 [분량] 지침(대략 600~950자)과 같은 기준으로 확인한다.
    assert 600 <= len(GOOD_NOTEBOOKLM["script"]) <= 950
