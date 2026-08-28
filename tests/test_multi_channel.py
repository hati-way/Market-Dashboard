"""pipeline/multi_channel.py(신규 다채널 생성 파이프라인) 통합 테스트.

pipeline/orchestrator.py(WordPress 파이프라인, --publish)와 완전히
독립적이다 - 이 테스트는 orchestrator.py를 전혀 쓰지 않는다. 실제
Anthropic API는 호출하지 않는다(FakeLlmClient).
"""
import json
import os
import shutil

import pytest

from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.wordpress_writer.generator import generate_wordpress_content
from pipeline.multi_channel import (
    ALL_CHANNELS,
    MultiChannelInputError,
    RunAlreadyExistsError,
    generate_channels,
)

from .conftest import FakeLlmClient
from .test_channel_generators_llm import (
    GOOD_NOTEBOOKLM,
    GOOD_THREADS,
    GOOD_THUMBNAIL,
    GOOD_YOUTUBE,
)

EXTENDED_INPUT = "data/input/sample_treasury_buyback.json"
TEST_OUTPUT_DIR = "data/output"


def _all_channel_responses() -> list[str]:
    return [
        json.dumps(GOOD_THREADS, ensure_ascii=False),
        json.dumps(GOOD_NOTEBOOKLM, ensure_ascii=False),
        json.dumps(GOOD_YOUTUBE, ensure_ascii=False),
        json.dumps(GOOD_THUMBNAIL, ensure_ascii=False),
    ]


def _cleanup(run_id: str) -> None:
    shutil.rmtree(os.path.join(TEST_OUTPUT_DIR, run_id), ignore_errors=True)


# ---- 1. MasterContent 하나로 5채널(WordPress + 4개 신규 채널) 생성 ----


def test_all_channels_share_the_same_master_content(fake_llm_client):
    """같은 MasterContent(같은 topic/meta.id)로 WordPress와 4개 신규 채널을
    각각 독립적으로 생성해도 모두 같은 사실 원본을 근거로 한다 - 어느
    채널도 WordPressArticle을 거치지 않는다(직접 만든 각 채널의
    used_fact_ids가 모두 원본 fixture의 facts 안에서만 나온다).
    """
    input_data = load_market_content_input_from_json_file(EXTENDED_INPUT)
    base_content = build_master_content(
        topic=input_data.topic, market_data=input_data.market_data, analysis=input_data.analysis
    )
    shared_id = base_content.meta.id

    wp_content = generate_wordpress_content(base_content.model_copy(deep=True), llm_client=fake_llm_client)
    assert wp_content.meta.id == shared_id

    run_id = "test-shared-master-content"
    _cleanup(run_id)
    try:
        fake_client = FakeLlmClient(responses=_all_channel_responses())
        manifest = generate_channels(
            EXTENDED_INPUT,
            list(ALL_CHANNELS),
            llm_client=fake_client,
            run_id=run_id,
            output_dir=TEST_OUTPUT_DIR,
        )
        assert manifest["topic"] == input_data.topic
        for channel in ALL_CHANNELS:
            assert manifest["channels"][channel]["status"] in ("PASS", "REVIEW_REQUIRED")
    finally:
        _cleanup(run_id)


# ---- 10. 한 채널 실패해도 나머지는 저장 ----


def test_one_channel_failure_does_not_discard_others():
    run_id = "test-partial-failure"
    _cleanup(run_id)
    try:
        broken_notebooklm = "이것은 JSON이 아닙니다."
        fake_client = FakeLlmClient(
            responses=[
                json.dumps(GOOD_THREADS, ensure_ascii=False),
                broken_notebooklm,
                json.dumps(GOOD_YOUTUBE, ensure_ascii=False),
                json.dumps(GOOD_THUMBNAIL, ensure_ascii=False),
            ]
        )
        manifest = generate_channels(
            EXTENDED_INPUT,
            list(ALL_CHANNELS),
            llm_client=fake_client,
            run_id=run_id,
            output_dir=TEST_OUTPUT_DIR,
        )

        assert manifest["channels"]["threads"]["status"] in ("PASS", "REVIEW_REQUIRED")
        assert manifest["channels"]["youtube"]["status"] in ("PASS", "REVIEW_REQUIRED")
        assert manifest["channels"]["thumbnail"]["status"] in ("PASS", "REVIEW_REQUIRED")
        assert os.path.exists(manifest["channels"]["threads"]["output_file"])
        assert os.path.exists(manifest["channels"]["youtube"]["output_file"])
        assert os.path.exists(manifest["channels"]["thumbnail"]["output_file"])

        assert manifest["channels"]["notebooklm"]["status"] == "FAIL"
        assert manifest["channels"]["notebooklm"]["output_file"] is None
        assert manifest["channels"]["notebooklm"]["reason"]
        assert not os.path.exists(os.path.join(TEST_OUTPUT_DIR, run_id, "notebooklm.json"))
    finally:
        _cleanup(run_id)


def test_master_content_build_failure_aborts_entire_run(tmp_path):
    """MasterContent 자체를 만들지 못하면(topic 없음) 부분 저장 없이 전체
    중단해야 한다 - 개별 채널 실패와 다르게 처리된다.
    """
    bad_input = tmp_path / "no_topic.json"
    bad_input.write_text(json.dumps({"market_data": {"as_of_date": "2026-01-01"}}), encoding="utf-8")

    run_id = "test-master-content-failure"
    _cleanup(run_id)
    try:
        with pytest.raises(MultiChannelInputError):
            generate_channels(
                str(bad_input),
                ["threads"],
                run_id=run_id,
                output_dir=TEST_OUTPUT_DIR,
            )
        # master_content.json조차 만들어지지 않아야 한다(전체 중단이므로).
        assert not os.path.exists(os.path.join(TEST_OUTPUT_DIR, run_id, "master_content.json"))
    finally:
        _cleanup(run_id)


# ---- 11. manifest 생성 ----


def test_manifest_json_is_written_with_expected_fields():
    run_id = "test-manifest-fields"
    _cleanup(run_id)
    try:
        fake_client = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))
        manifest = generate_channels(
            EXTENDED_INPUT,
            ["threads"],
            llm_client=fake_client,
            run_id=run_id,
            output_dir=TEST_OUTPUT_DIR,
        )

        manifest_path = os.path.join(TEST_OUTPUT_DIR, run_id, "manifest.json")
        assert os.path.exists(manifest_path)
        on_disk = json.loads(open(manifest_path, encoding="utf-8").read())

        for key in ("run_id", "topic", "generated_at", "channels", "usage", "master_content_file"):
            assert key in on_disk
        assert on_disk["run_id"] == run_id
        assert on_disk == manifest
    finally:
        _cleanup(run_id)


# ---- 12. run_id 공유(모든 채널 산출물이 같은 run_id 아래에 저장됨) ----


def test_all_channel_outputs_share_the_same_run_id_directory():
    run_id = "test-shared-run-id"
    _cleanup(run_id)
    try:
        fake_client = FakeLlmClient(responses=_all_channel_responses())
        manifest = generate_channels(
            EXTENDED_INPUT,
            list(ALL_CHANNELS),
            llm_client=fake_client,
            run_id=run_id,
            output_dir=TEST_OUTPUT_DIR,
        )

        run_dir = os.path.join(TEST_OUTPUT_DIR, run_id)
        assert os.path.exists(os.path.join(run_dir, "master_content.json"))
        assert os.path.exists(os.path.join(run_dir, "manifest.json"))
        for channel in ALL_CHANNELS:
            info = manifest["channels"][channel]
            assert info["output_file"].startswith(run_dir)
    finally:
        _cleanup(run_id)


# ---- 13. --force 없이는 기존 결과 덮어쓰기 금지 ----


def test_rerunning_same_run_id_without_force_raises():
    run_id = "test-no-overwrite"
    _cleanup(run_id)
    try:
        fake_client = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))
        generate_channels(
            EXTENDED_INPUT, ["threads"], llm_client=fake_client, run_id=run_id, output_dir=TEST_OUTPUT_DIR
        )

        fake_client_2 = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))
        with pytest.raises(RunAlreadyExistsError):
            generate_channels(
                EXTENDED_INPUT,
                ["threads"],
                llm_client=fake_client_2,
                run_id=run_id,
                output_dir=TEST_OUTPUT_DIR,
            )
    finally:
        _cleanup(run_id)


def test_rerunning_same_run_id_with_force_overwrites():
    run_id = "test-force-overwrite"
    _cleanup(run_id)
    try:
        fake_client = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))
        generate_channels(
            EXTENDED_INPUT, ["threads"], llm_client=fake_client, run_id=run_id, output_dir=TEST_OUTPUT_DIR
        )

        fake_client_2 = FakeLlmClient(json.dumps(GOOD_THREADS, ensure_ascii=False))
        manifest = generate_channels(
            EXTENDED_INPUT,
            ["threads"],
            llm_client=fake_client_2,
            run_id=run_id,
            output_dir=TEST_OUTPUT_DIR,
            force=True,
        )
        assert manifest["channels"]["threads"]["status"] in ("PASS", "REVIEW_REQUIRED")
    finally:
        _cleanup(run_id)


# ---- 14. token usage 기록 ----


def test_usage_is_recorded_per_channel():
    run_id = "test-usage-tracking"
    _cleanup(run_id)
    try:
        fake_client = FakeLlmClient(responses=_all_channel_responses())
        manifest = generate_channels(
            EXTENDED_INPUT,
            list(ALL_CHANNELS),
            llm_client=fake_client,
            run_id=run_id,
            output_dir=TEST_OUTPUT_DIR,
        )

        assert len(manifest["usage"]) == len(ALL_CHANNELS)
        recorded_channels = {u["channel"] for u in manifest["usage"]}
        assert recorded_channels == set(ALL_CHANNELS)
        for record in manifest["usage"]:
            assert record["provider"] == "anthropic"
            assert record["model"]
            assert record["input_tokens"] is not None
            assert record["output_tokens"] is not None
    finally:
        _cleanup(run_id)


# ---- 15. 실제 API 없이 FakeLlmClient로 --generate-all 전체 통합 테스트 ----


def test_generate_all_channels_end_to_end_with_fake_llm_client():
    run_id = "test-generate-all"
    _cleanup(run_id)
    try:
        fake_client = FakeLlmClient(responses=_all_channel_responses())
        manifest = generate_channels(
            EXTENDED_INPUT,
            list(ALL_CHANNELS),
            llm_client=fake_client,
            run_id=run_id,
            output_dir=TEST_OUTPUT_DIR,
        )

        assert manifest["run_id"] == run_id
        assert all(
            manifest["channels"][c]["status"] in ("PASS", "REVIEW_REQUIRED") for c in ALL_CHANNELS
        )
        for channel in ALL_CHANNELS:
            output_path = manifest["channels"][channel]["output_file"]
            data = json.loads(open(output_path, encoding="utf-8").read())
            assert data["used_fact_ids"]
    finally:
        _cleanup(run_id)
