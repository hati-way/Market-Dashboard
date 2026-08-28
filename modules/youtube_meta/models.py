"""YouTube 메타데이터 생성기(LLM)의 구조화된 출력 스키마."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

TITLE_CANDIDATE_COUNT = 5
MIN_TAGS = 5
MAX_TAGS = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class YouTubeOutput(BaseModel):
    title_candidates: list[str]
    recommended_title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    pinned_comment: str
    used_fact_ids: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now_iso)

    @field_validator("title_candidates")
    @classmethod
    def _validate_title_candidates(cls, value: list[str]) -> list[str]:
        if len(value) != TITLE_CANDIDATE_COUNT:
            raise ValueError(
                f"title_candidates는 {TITLE_CANDIDATE_COUNT}개여야 합니다(현재 {len(value)}개)."
            )
        return value

    @field_validator("recommended_title")
    @classmethod
    def _validate_recommended_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("recommended_title이 비어 있습니다.")
        return value

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: list[str]) -> list[str]:
        if not (MIN_TAGS <= len(value) <= MAX_TAGS):
            raise ValueError(f"tags는 {MIN_TAGS}~{MAX_TAGS}개여야 합니다(현재 {len(value)}개).")
        seen: set[str] = set()
        for tag in value:
            normalized = tag.strip().lower()
            if normalized in seen:
                raise ValueError(f"중복되는 tag가 있습니다: {tag!r}")
            seen.add(normalized)
        return value
