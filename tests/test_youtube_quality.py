"""YouTube 채널 생성 품질 개선 회귀 테스트.

실제 --generate-all 실행에서 pinned_comment에 "fact_001" 같은 내부
fact id가 노출된 문제, tags 개수 미제한, chapters가 항상 빈 목록으로
저장되던 문제를 다룬다. Threads/NotebookLM/Thumbnail은 건드리지
않았다.
"""
import json

import pytest
from pydantic import ValidationError

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.notebooklm_script.generator import generate_notebooklm_output
from modules.youtube_meta.generator import (
    MAX_CHAPTERS,
    MIN_CHAPTERS,
    YoutubeGenerationError,
    YoutubeInternalIdLeakError,
    _check_no_internal_ids_leaked,
    _derive_chapter_titles_from_master_content,
    _generate_chapter_candidates,
    generate_youtube_output,
)
from modules.youtube_meta.models import MAX_TAGS, MIN_TAGS, YouTubeOutput

from .conftest import FakeLlmClient
from .test_channel_generators_llm import GOOD_NOTEBOOKLM, GOOD_YOUTUBE

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"


def _load_treasury_content():
    input_data = load_market_content_input_from_json_file(EXTENDED_INPUT)
    return build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )


# ---- 1~2. 사용자 노출 필드에 내부 fact id가 있으면 FAIL ----


def test_internal_id_leak_detected_in_pinned_comment():
    output = YouTubeOutput.model_validate(
        {**GOOD_YOUTUBE, "pinned_comment": "핵심 근거: fact_001, fact_002"}
    )
    with pytest.raises(YoutubeInternalIdLeakError, match="pinned_comment"):
        _check_no_internal_ids_leaked(output)


def test_internal_id_leak_detected_in_description():
    output = YouTubeOutput.model_validate(
        {**GOOD_YOUTUBE, "description": GOOD_YOUTUBE["description"] + "\n(근거: fact_003)"}
    )
    with pytest.raises(YoutubeInternalIdLeakError, match="description"):
        _check_no_internal_ids_leaked(output)


def test_internal_id_leak_detected_in_title_candidate():
    candidates = list(GOOD_YOUTUBE["title_candidates"])
    candidates[0] = candidates[0] + " (fact_001)"
    output = YouTubeOutput.model_validate({**GOOD_YOUTUBE, "title_candidates": candidates})
    with pytest.raises(YoutubeInternalIdLeakError, match=r"title_candidates\[0\]"):
        _check_no_internal_ids_leaked(output)


def test_clean_output_does_not_trigger_leak_error():
    output = YouTubeOutput.model_validate(GOOD_YOUTUBE)
    _check_no_internal_ids_leaked(output)  # 예외가 나지 않아야 한다.


def test_generation_fails_when_pinned_comment_leaks_fact_id_on_both_attempts():
    """실제 보고된 시나리오 재현: pinned_comment에 fact id가 노출되면
    schema-repair 재시도까지 거쳐도(둘 다 같은 문제면) 최종적으로
    막혀야 한다.
    """
    content = _load_treasury_content()
    leaking = {**GOOD_YOUTUBE, "pinned_comment": "핵심 근거: fact_001, fact_002"}
    fake_client = FakeLlmClient(
        responses=[json.dumps(leaking, ensure_ascii=False), json.dumps(leaking, ensure_ascii=False)]
    )

    with pytest.raises(YoutubeGenerationError):
        generate_youtube_output(content, llm_client=fake_client)
    assert len(fake_client.calls) == 2  # 무한 재시도가 아니라 정확히 2회에서 멈춰야 한다.


def test_generation_recovers_when_repair_attempt_removes_leaked_id():
    content = _load_treasury_content()
    leaking = {**GOOD_YOUTUBE, "pinned_comment": "핵심 근거: fact_001, fact_002"}
    fake_client = FakeLlmClient(
        responses=[json.dumps(leaking, ensure_ascii=False), json.dumps(GOOD_YOUTUBE, ensure_ascii=False)]
    )

    result = generate_youtube_output(content, llm_client=fake_client)

    assert "fact_" not in result.youtube.pinned_comment.lower()
    assert len(fake_client.calls) == 2


# ---- 3. tags 5~8개, 중복 없음 ----


def test_tags_model_rejects_too_few_or_too_many():
    with pytest.raises(ValidationError):
        YouTubeOutput.model_validate({**GOOD_YOUTUBE, "tags": ["a", "b", "c"]})
    with pytest.raises(ValidationError):
        YouTubeOutput.model_validate({**GOOD_YOUTUBE, "tags": [f"tag{i}" for i in range(9)]})

    ok = YouTubeOutput.model_validate(GOOD_YOUTUBE)
    assert MIN_TAGS <= len(ok.tags) <= MAX_TAGS


def test_tags_model_rejects_case_insensitive_duplicates():
    with pytest.raises(ValidationError):
        YouTubeOutput.model_validate(
            {**GOOD_YOUTUBE, "tags": ["미국국채", "미국국채", "국채금리", "재무부", "거시경제"]}
        )


# ---- 6~7. chapters 후보 생성(NotebookLM 우선, 없으면 MasterContent 구조) ----


def test_chapters_derived_from_notebooklm_script_when_present():
    content = _load_treasury_content()
    content = generate_notebooklm_output(
        content, llm_client=FakeLlmClient(json.dumps(GOOD_NOTEBOOKLM, ensure_ascii=False))
    )
    assert content.notebooklm.chapters  # 전제 조건: notebooklm이 먼저 실행됨

    content = generate_youtube_output(
        content, llm_client=FakeLlmClient(json.dumps(GOOD_YOUTUBE, ensure_ascii=False))
    )

    assert MIN_CHAPTERS <= len(content.youtube.chapters) <= MAX_CHAPTERS
    # notebooklm의 챕터 제목 중 일부가 그대로(또는 대표로) 쓰였는지 확인한다.
    chapter_titles = {c.title for c in content.youtube.chapters}
    assert chapter_titles & set(GOOD_NOTEBOOKLM["chapters"])


def test_chapters_derived_from_master_content_when_notebooklm_absent():
    content = _load_treasury_content()
    assert not content.notebooklm.chapters  # 전제 조건: notebooklm 미실행

    content = generate_youtube_output(
        content, llm_client=FakeLlmClient(json.dumps(GOOD_YOUTUBE, ensure_ascii=False))
    )

    assert MIN_CHAPTERS <= len(content.youtube.chapters) <= MAX_CHAPTERS
    for chapter in content.youtube.chapters:
        assert chapter.timestamp
        assert chapter.title
        # 챕터 제목이 짧고 자연스러운 한국어여야 한다(영어/내부 식별자 없음).
        assert "fact_" not in chapter.title.lower()


def test_chapter_timestamps_are_strictly_increasing():
    content = _load_treasury_content()
    content = generate_youtube_output(
        content, llm_client=FakeLlmClient(json.dumps(GOOD_YOUTUBE, ensure_ascii=False))
    )

    def to_seconds(ts: str) -> int:
        minutes, seconds = ts.split(":")
        return int(minutes) * 60 + int(seconds)

    seconds = [to_seconds(c.timestamp) for c in content.youtube.chapters]
    assert seconds == sorted(seconds)
    assert len(seconds) == len(set(seconds))  # 중복 타임스탬프 없음


def test_derive_chapter_titles_skips_empty_sections_without_fabricating():
    content = _load_treasury_content()
    content.analysis.bull_case = []
    content.analysis.bear_case = []
    content.analysis.risks = []
    content.analysis.update_triggers = []

    titles = _derive_chapter_titles_from_master_content(content)

    assert "긍정과 위험 요인" not in titles
    assert "주요 리스크" not in titles
    assert "앞으로 확인할 지표" not in titles
    assert titles[0] == "핵심 답변"
    assert titles[-1] == "핵심 요약"


def test_generate_chapter_candidates_returns_empty_when_nothing_available():
    content = _load_treasury_content()
    content.market_data.macro_events = []
    content.analysis.facts = []
    content.analysis.causal_chain = []
    content.analysis.market_implications = []
    content.analysis.bull_case = []
    content.analysis.bear_case = []
    content.analysis.risks = []
    content.analysis.update_triggers = []

    chapters = _generate_chapter_candidates(content)

    # "핵심 답변"/"핵심 요약"은 항상 있으므로 완전히 비지는 않지만,
    # 근거 없는 섹션을 억지로 채워 4개 이상으로 부풀리지 않아야 한다.
    assert len(chapters) == 2
    assert [c.title for c in chapters] == ["핵심 답변", "핵심 요약"]


# ---- 9. 기존 Fact Grounding 유지 확인 ----


def test_fact_grounding_and_hallucination_checks_still_work():
    content = _load_treasury_content()

    # 존재하지 않는 fact id -> FAIL 계열 예외.
    bad = {**GOOD_YOUTUBE, "used_fact_ids": ["fact_999"]}
    with pytest.raises(YoutubeGenerationError):
        generate_youtube_output(content, llm_client=FakeLlmClient(json.dumps(bad, ensure_ascii=False)))

    # 근거 없는 소수점 숫자 -> 여전히 차단.
    hallucinated = {**GOOD_YOUTUBE, "description": GOOD_YOUTUBE["description"] + " 650.12를 기록했다."}
    with pytest.raises(YoutubeGenerationError):
        generate_youtube_output(
            content, llm_client=FakeLlmClient(json.dumps(hallucinated, ensure_ascii=False))
        )


def test_low_confidence_fact_still_triggers_review_required_without_leaking_id():
    content = _load_treasury_content()
    with_low_confidence = {
        **GOOD_YOUTUBE,
        "pinned_comment": (
            GOOD_YOUTUBE["pinned_comment"]
            + " 일부 시장 참여자는 유동성 부담이 완화될 가능성이 있다고 본다."
        ),
        "used_fact_ids": [*GOOD_YOUTUBE["used_fact_ids"], "fact_004"],
    }
    fake_client = FakeLlmClient(json.dumps(with_low_confidence, ensure_ascii=False))

    result = generate_youtube_output(content, llm_client=fake_client)

    assert result.youtube.fact_validation_status == "REVIEW_REQUIRED"
    assert "fact_" not in result.youtube.pinned_comment.lower()
    assert "일부 시장 참여자" in result.youtube.pinned_comment
