"""6단계: MasterContent 하나로 여러 채널(Threads/NotebookLM/YouTube/
Thumbnail) 산출물을 생성하는 다채널 파이프라인.

pipeline/orchestrator.py(WordPress 중심 단일 파이프라인, --publish)와는
완전히 분리되어 있다 - 이 파이프라인은 orchestrator.py를 호출하지
않고, orchestrator.py도 이 파이프라인을 호출하지 않는다. 각 채널은
WordPressArticle을 거치지 않고 MasterContent.market_data/analysis를
직접 입력받는다(WordPress의 해석 오류/문체가 다른 채널로 전파되는 것을
막기 위함).

구조:
    MasterContent
    ├→ Threads   (modules.threads_writer.generator.generate_threads_output)
    ├→ NotebookLM(modules.notebooklm_script.generator.generate_notebooklm_output)
    ├→ YouTube   (modules.youtube_meta.generator.generate_youtube_output)
    └→ Thumbnail (modules.thumbnail_prompt.generator.generate_thumbnail_output)

한 채널이 실패해도(구조 검증 실패, Fact Grounding FAIL, LLM 호출
오류 등) 전체 실행을 중단하지 않고 나머지 채널은 계속 생성/저장한다.
단, MasterContent 자체를 만들지 못하면(topic 누락, 입력 파일 오류 등)
전체를 중단한다. 실행 결과는 data/output/{run_id}/ 아래에 채널별
JSON + manifest.json으로 저장한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from clients.llm_client import LlmClient, LlmClientError
from modules.data_ingest.ingest import load_market_content_input_from_json_file
from modules.master_content.builder import build_master_content
from modules.master_content.schema import MasterContent
from modules.notebooklm_script.generator import (
    NotebookLmGenerationError,
    generate_notebooklm_output,
)
from modules.thumbnail_prompt.generator import ThumbnailGenerationError, generate_thumbnail_output
from modules.threads_writer.generator import ThreadsGenerationError, generate_threads_output
from modules.youtube_meta.generator import YoutubeGenerationError, generate_youtube_output

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/output")

ALL_CHANNELS: tuple[str, ...] = ("threads", "notebooklm", "youtube", "thumbnail")

# 채널 이름 -> (생성 함수, 실패로 간주할 예외 클래스, MasterContent에서
# 결과를 읽을 필드 이름).
_CHANNEL_SPECS: dict[str, tuple] = {
    "threads": (generate_threads_output, ThreadsGenerationError, "threads"),
    "notebooklm": (generate_notebooklm_output, NotebookLmGenerationError, "notebooklm"),
    "youtube": (generate_youtube_output, YoutubeGenerationError, "youtube"),
    "thumbnail": (generate_thumbnail_output, ThumbnailGenerationError, "thumbnail"),
}


class MultiChannelInputError(Exception):
    """MasterContent 자체를 만들지 못했을 때(topic 누락, 입력 파일 오류 등)
    발생한다 - 이 경우에만 전체 실행을 중단한다.
    """


class RunAlreadyExistsError(Exception):
    """같은 run_id의 결과가 이미 있는데 --force 없이 다시 생성하려 할 때 발생한다."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]


def _build_content(market_data_path: str | Path, topic: str | None) -> MasterContent:
    input_data = load_market_content_input_from_json_file(market_data_path)
    resolved_topic = topic or input_data.topic
    if not resolved_topic:
        raise MultiChannelInputError(
            "topic이 필요합니다. --topic 을 넘기거나, 입력 파일에 \"topic\" 필드를 넣어주세요."
        )
    return build_master_content(
        topic=resolved_topic, market_data=input_data.market_data, analysis=input_data.analysis
    )


def generate_channels(
    market_data_path: str | Path,
    channels: list[str],
    *,
    topic: str | None = None,
    llm_client: LlmClient | None = None,
    run_id: str | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    force: bool = False,
) -> dict:
    """요청한 채널들을 MasterContent 하나로부터 생성하고 저장한다.

    llm_client를 넘기지 않으면 채널마다 실제 Anthropic API를 호출하는
    LlmClient()를 새로 만든다(테스트에서는 가짜 client를 주입한다).
    같은 llm_client 인스턴스를 모든 채널이 공유한다.

    반환값은 manifest.json과 동일한 구조의 dict다.
    """
    unknown = [c for c in channels if c not in _CHANNEL_SPECS]
    if unknown:
        raise ValueError(f"알 수 없는 채널입니다: {unknown} (허용: {list(_CHANNEL_SPECS)})")

    run_id = run_id or _new_run_id()
    run_dir = Path(output_dir) / run_id
    manifest_path = run_dir / "manifest.json"

    if manifest_path.exists() and not force:
        raise RunAlreadyExistsError(
            f"run_id '{run_id}'의 결과가 이미 존재합니다 ({manifest_path}). "
            "덮어쓰려면 --force를 사용하세요."
        )

    run_dir.mkdir(parents=True, exist_ok=True)

    # MasterContent 자체를 만들지 못하면 전체 중단(요구사항 9).
    content = _build_content(market_data_path, topic)

    master_content_path = run_dir / "master_content.json"
    master_content_path.write_text(
        json.dumps(content.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    usage_log: list[dict] = []
    channel_manifest: dict[str, dict] = {}

    for channel in channels:
        generator, error_cls, field_name = _CHANNEL_SPECS[channel]
        output_path = run_dir / f"{channel}.json"
        try:
            content = generator(content, llm_client=llm_client, usage_log=usage_log)
        except (error_cls, LlmClientError) as exc:
            logger.warning("%s 채널 생성 실패: %s", channel, exc)
            channel_manifest[channel] = {
                "status": "FAIL",
                "reason": str(exc),
                "output_file": None,
            }
            continue
        except Exception as exc:  # noqa: BLE001 - 채널 하나의 실패로 전체 실행을 막지 않는다.
            logger.warning("%s 채널 생성 중 예상치 못한 오류: %s", channel, exc)
            channel_manifest[channel] = {
                "status": "FAIL",
                "reason": f"예상치 못한 오류: {exc}",
                "output_file": None,
            }
            continue

        channel_content = getattr(content, field_name)
        output_path.write_text(
            json.dumps(channel_content.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        channel_manifest[channel] = {
            "status": channel_content.fact_validation_status or "PASS",
            "reason": "",
            "output_file": str(output_path),
        }

    manifest = {
        "run_id": run_id,
        "topic": content.meta.topic,
        "generated_at": _now_iso(),
        "channels": channel_manifest,
        "usage": usage_log,
        "master_content_file": str(master_content_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return manifest
