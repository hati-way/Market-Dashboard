"""5단계: Quality Gate / Publication Decision 결과를 받아 WordPress에 발행한다.

기본값은 항상 안전한 쪽이다.

- WORDPRESS_DRY_RUN=true(기본값): WordPress API를 전혀 호출하지 않고
  "실제로 했다면 무엇을 했을지"만 돌려준다.
- WORDPRESS_DRAFT_FIRST=true(기본값): PASS 판정이어도 곧바로 공개
  발행(publish)하지 않고 draft로만 만든다. 운영자가 .env에서 의도적으로
  WORDPRESS_DRAFT_FIRST=false 로 바꿔야 PASS가 실제 publish로 이어진다.
- Quality Gate가 FAIL(=PublicationDecision.recommended_status가
  blocked)이면 dry-run 여부와 무관하게 WordPress API를 절대 호출하지
  않는다.
- REVIEW_REQUIRED는 draft-first 설정과 무관하게 항상 draft다.

로그에는 pipeline 단계, title/slug, quality status, WordPress 응답
상태, post id 정도만 남기고, WORDPRESS_APP_PASSWORD/Authorization
헤더/Anthropic API 키 같은 인증정보는 절대 남기지 않는다
(clients/wordpress_client.py 도 마찬가지 원칙을 따른다).
"""
from __future__ import annotations

import logging

from clients.wordpress_client import WordPressClient
from config.settings import get_settings
from modules.master_content.schema import MasterContent, PublishResult
from modules.quality_gate.models import PublicationDecision, QualityGateResult, RecommendedStatus

from .models import PublishAction, PublishOutcome

logger = logging.getLogger(__name__)


def resolve_wordpress_status(decision: PublicationDecision, draft_first: bool) -> str | None:
    """WordPress에 만들 post의 status("draft"/"publish")를 정한다.

    None이면 아무것도 만들지 않는다(=blocked). pipeline/quality_report.py의
    CLI 리포트도 이 함수를 그대로 가져다 써서, 화면에 보여주는 "WordPress
    예정 status"가 실제 발행 로직과 어긋나는 일이 없게 한다.
    """
    if decision.recommended_status == RecommendedStatus.BLOCKED:
        return None
    if decision.recommended_status == RecommendedStatus.DRAFT:
        return "draft"
    # PUBLISH: draft-first가 켜져 있으면 곧바로 공개하지 않고 draft로 낮춘다.
    return "draft" if draft_first else "publish"


def publish_to_wordpress(
    content: MasterContent,
    gate_result: QualityGateResult,
    decision: PublicationDecision,
    *,
    client: WordPressClient | None = None,
    dry_run: bool | None = None,
    draft_first: bool | None = None,
    existing_post_policy: str | None = None,
) -> PublishOutcome:
    """Quality Gate 판정을 받아 WordPress에 발행(또는 draft 생성)한다.

    client 를 넘기지 않으면(그리고 dry_run이 아니면) 실제 WordPress API를
    호출하는 WordPressClient()를 새로 만든다. dry_run/draft_first/
    existing_post_policy 를 넘기지 않으면 .env 설정값을 따른다.

    content.publish(PublishResult)도 함께 갱신하고, 더 자세한 정보를
    담은 PublishOutcome을 반환한다.
    """
    settings = get_settings()
    if dry_run is None:
        dry_run = settings.wordpress_dry_run
    if draft_first is None:
        draft_first = settings.wordpress_draft_first
    if existing_post_policy is None:
        existing_post_policy = settings.wordpress_existing_post_policy

    wp = content.wordpress
    quality_status = gate_result.status.value

    # FAIL(blocked)은 dry-run 여부와 무관하게 절대 WordPress API를 부르지 않는다.
    if decision.recommended_status == RecommendedStatus.BLOCKED:
        content.publish = PublishResult(published=False)
        content.touch()
        logger.info("WordPress 발행 차단(blocked): slug=%s quality_status=%s", wp.slug, quality_status)
        return PublishOutcome(
            dry_run=dry_run,
            action=PublishAction.BLOCKED,
            wordpress_status=None,
            title=wp.title,
            slug=wp.slug,
            quality_status=quality_status,
            reason=decision.reason or "Quality Gate FAIL",
            warnings=gate_result.warnings,
            recommendations=gate_result.recommendations,
        )

    wordpress_status = resolve_wordpress_status(decision, draft_first)

    if dry_run:
        logger.info(
            "[dry-run] WordPress %s 예정: slug=%s quality_status=%s",
            wordpress_status, wp.slug, quality_status,
        )
        return PublishOutcome(
            dry_run=True,
            action=PublishAction.DRY_RUN,
            wordpress_status=wordpress_status,
            title=wp.title,
            slug=wp.slug,
            quality_status=quality_status,
            reason="dry-run: WordPress API를 호출하지 않았습니다.",
            warnings=gate_result.warnings,
            recommendations=gate_result.recommendations,
        )

    wp_client = client or WordPressClient()

    existing = wp_client.find_post_by_slug(wp.slug) if wp.slug else None

    if existing:
        existing_status = existing.get("status")
        existing_id = existing.get("id")
        if existing_status == "publish" or existing_post_policy != "draft_update":
            # 이미 발행된 글은 이번 단계에서 절대 자동 수정하지 않는다.
            # (draft_update 정책이어도 기존 글이 이미 publish 상태면 건드리지 않는다.)
            reason = (
                "이미 발행된 글은 자동으로 수정하지 않습니다."
                if existing_status == "publish"
                else f"동일 slug의 글이 이미 있어 건너뜁니다 (policy={existing_post_policy})."
            )
            content.publish = PublishResult(
                published=(existing_status == "publish"), post_id=existing_id, post_url=existing.get("link")
            )
            content.touch()
            logger.info("WordPress 발행 건너뜀(skipped): slug=%s post_id=%s", wp.slug, existing_id)
            return PublishOutcome(
                dry_run=False,
                action=PublishAction.SKIPPED,
                wordpress_status=existing_status,
                post_id=existing_id,
                url=existing.get("link"),
                title=wp.title,
                slug=wp.slug,
                quality_status=quality_status,
                reason=reason,
                warnings=gate_result.warnings,
                recommendations=gate_result.recommendations,
            )

        # existing_post_policy == "draft_update" 이고 기존 글이 draft(등)일 때만 갱신.
        response = wp_client.update_post(
            existing_id,
            title=wp.title,
            content_html=wp.content_html,
            excerpt=wp.excerpt,
            slug=wp.slug,
            status=wordpress_status,
        )
        action = PublishAction.UPDATED
    else:
        response = wp_client.create_post(
            title=wp.title,
            content_html=wp.content_html,
            excerpt=wp.excerpt,
            slug=wp.slug,
            status=wordpress_status,
        )
        action = PublishAction.CREATED

    post_id = response.get("id")
    post_url = response.get("link")
    response_status = response.get("status", wordpress_status)

    content.publish = PublishResult(
        published=(response_status == "publish"),
        post_id=post_id,
        post_url=post_url,
        published_at=response.get("date") if response_status == "publish" else None,
    )
    content.touch()

    logger.info(
        "WordPress %s: post_id=%s status=%s slug=%s",
        action.value, post_id, response_status, wp.slug,
    )
    return PublishOutcome(
        dry_run=False,
        action=action,
        wordpress_status=response_status,
        post_id=post_id,
        url=post_url,
        title=wp.title,
        slug=wp.slug,
        quality_status=quality_status,
        reason="",
        warnings=gate_result.warnings,
        recommendations=gate_result.recommendations,
    )
