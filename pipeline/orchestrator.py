"""전체 파이프라인(1~10단계)을 순서대로 실행한다.

3단계(WordPress 글 생성)까지 끝나면, --publish 가 켜져 있을 때만
Fact Grounding → Quality Gate → Publication Decision → WordPress 발행
(또는 dry-run/draft)까지 이어서 실행한다. publish가 꺼져 있으면(기본값)
이 단계는 아예 건드리지 않아 기존 동작(4단계까지만)과 동일하다.

WordPress credential이 없는 테스트/개발 환경에서도 안전하게 동작하도록,
기본값은 dry_run=True(.env의 WORDPRESS_DRY_RUN)다 — 실제 WordPress API를
전혀 호출하지 않는다. llm_client와 마찬가지로 wordpress_client도
주입할 수 있어(dependency injection) 테스트에서 실제 API를 부르지
않게 할 수 있다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from clients.llm_client import LlmClient
from clients.wordpress_client import WordPressClient
from modules.data_ingest.ingest import load_market_data_from_json_file
from modules.master_content.builder import build_master_content, save_master_content
from modules.master_content.schema import MasterContent
from modules.notebooklm_script.generator import generate_notebooklm_script
from modules.quality_check.checker import run_quality_check
from modules.quality_gate.gate import decide_publication, run_quality_gate_for_content
from modules.thumbnail_prompt.generator import generate_thumbnail_assets
from modules.threads_writer.generator import generate_threads_content
from modules.wordpress_publisher.publisher import publish_to_wordpress
from modules.wordpress_writer.generator import generate_wordpress_content
from modules.youtube_meta.generator import generate_youtube_meta

logger = logging.getLogger(__name__)


def run_pipeline(
    topic: str,
    market_data_path: str | Path,
    publish: bool = False,
    llm_client: LlmClient | None = None,
    wordpress_client: WordPressClient | None = None,
    dry_run: bool | None = None,
    draft_first: bool | None = None,
) -> MasterContent:
    """llm_client 를 넘기지 않으면 3단계에서 실제 Anthropic API를 호출하는
    LlmClient()를 새로 만든다 (테스트에서는 가짜 client를 주입한다).

    publish=True 일 때만 5단계(Quality Gate → Publication Decision →
    WordPress 발행)를 실행한다. wordpress_client/dry_run/draft_first를
    넘기지 않으면 .env 설정값을 따른다(기본값은 항상 안전한 dry-run +
    draft-first).
    """
    # 1. 데이터 입력
    market_data = load_market_data_from_json_file(market_data_path)

    # 2. Master Content JSON 구조화
    content = build_master_content(topic=topic, market_data=market_data)

    # 3. WordPress 분석글 생성 (Fact Grounding 검증까지 이 안에서 끝남)
    content = generate_wordpress_content(content, llm_client=llm_client)

    # 4. SEO/AEO/GEO/NEO 품질 검사 (기존, 규칙 기반 pass/fail)
    content = run_quality_check(content)

    # 5. Quality Gate → Publication Decision → WordPress 발행
    if publish:
        gate_result = run_quality_gate_for_content(content)
        decision = decide_publication(gate_result)
        outcome = publish_to_wordpress(
            content,
            gate_result,
            decision,
            client=wordpress_client,
            dry_run=dry_run,
            draft_first=draft_first,
        )
        logger.info(
            "WordPress 발행 결과: action=%s status=%s dry_run=%s quality_status=%s",
            outcome.action.value, outcome.wordpress_status, outcome.dry_run, outcome.quality_status,
        )

    # 6~9. 같은 Master JSON으로 다른 채널 콘텐츠 생성
    content = generate_threads_content(content)
    content = generate_notebooklm_script(content)
    content = generate_youtube_meta(content)
    content = generate_thumbnail_assets(content)

    # Master Content JSON 저장 (10단계 성과 기록은 발행 이후 별도 실행)
    saved_path = save_master_content(content)
    logger.info("Master Content 저장: %s", saved_path)

    return content
