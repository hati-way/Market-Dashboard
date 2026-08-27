"""publish_to_wordpress() 의 반환 모델."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PublishAction(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    DRY_RUN = "dry_run"


class PublishOutcome(BaseModel):
    """publish_to_wordpress() 의 반환값.

    dry_run=True 인 경우 action/wordpress_status 는 "실제로 했다면
    무엇을 했을지"를 나타내는 값일 뿐이며, 이 경우 WordPress API는
    전혀 호출되지 않는다.
    """

    dry_run: bool = False
    action: PublishAction
    wordpress_status: str | None = None
    post_id: int | None = None
    url: str | None = None
    title: str = ""
    slug: str = ""
    quality_status: str = ""
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
