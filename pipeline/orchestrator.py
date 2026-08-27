"""전체 파이프라인(1~10단계)을 순서대로 실행한다.

지금 단계에서 5단계(WordPress 발행)는 아직 미구현이므로, 품질 검사를
통과했고 --publish 옵션이 켜져 있어도 NotImplementedError 를 만나면
경고만 남기고 나머지 단계(6~9)는 계속 진행한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from clients.llm_client import LlmClient
from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content, save_master_content
from modules.master_content.schema import MasterContent
from modules.notebooklm_script.generator import generate_notebooklm_script
from modules.quality_check.checker import run_quality_check
from modules.thumbnail_prompt.generator import generate_thumbnail_assets
from modules.threads_writer.generator import generate_threads_content
from modules.wordpress_publisher.publisher import NotReadyToPublishError, publish_to_wordpress
from modules.wordpress_writer.generator import generate_wordpress_content
from modules.youtube_meta.generator import generate_youtube_meta

logger = logging.getLogger(__name__)


def run_pipeline(
    topic: str,
    market_data_path: str | Path,
    publish: bool = False,
    llm_client: LlmClient | None = None,
) -> MasterContent:
    """llm_client 를 넘기지 않으면 3단계에서 실제 Anthropic API를 호출하는
    LlmClient()를 새로 만든다 (테스트에서는 가짜 client를 주입한다).
    """
    # 1. 데이터 입력
    market_data = load_market_data_from_json_file(market_data_path)

    # 2. Master Content JSON 구조화
    content = build_master_content(topic=topic, market_data=market_data)

    # 3. WordPress 분석글 생성
    content = generate_wordpress_content(content, llm_client=llm_client)

    # 4. SEO/AEO/GEO/NEO 품질 검사
    content = run_quality_check(content)

    # 5. 통과한 콘텐츠만 발행 (아직 미구현이면 건너뛰고 계속 진행)
    if publish:
        try:
            content = publish_to_wordpress(content)
        except NotReadyToPublishError as exc:
            logger.warning("발행 건너뜀: %s", exc)
        except NotImplementedError as exc:
            logger.warning("발행 기능 미구현: %s", exc)

    # 6~9. 같은 Master JSON으로 다른 채널 콘텐츠 생성
    content = generate_threads_content(content)
    content = generate_notebooklm_script(content)
    content = generate_youtube_meta(content)
    content = generate_thumbnail_assets(content)

    # Master Content JSON 저장 (10단계 성과 기록은 발행 이후 별도 실행)
    saved_path = save_master_content(content)
    logger.info("Master Content 저장: %s", saved_path)

    return content
