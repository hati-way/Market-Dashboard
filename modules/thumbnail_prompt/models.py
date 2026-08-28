"""썸네일 문구/Midjourney 프롬프트 생성기(LLM)의 구조화된 출력 스키마."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

TEXT_CANDIDATE_COUNT = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ThumbnailOutput(BaseModel):
    thumbnail_text_candidates: list[str]
    recommended_text: str
    midjourney_prompt: str
    visual_concept: str
    avoid_elements: list[str] = Field(default_factory=list)
    used_fact_ids: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now_iso)

    @field_validator("thumbnail_text_candidates")
    @classmethod
    def _validate_text_candidates(cls, value: list[str]) -> list[str]:
        if len(value) != TEXT_CANDIDATE_COUNT:
            raise ValueError(
                f"thumbnail_text_candidates는 {TEXT_CANDIDATE_COUNT}개여야 합니다"
                f"(현재 {len(value)}개)."
            )
        return value

    @field_validator("midjourney_prompt")
    @classmethod
    def _validate_midjourney_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("midjourney_prompt가 비어 있습니다.")
        return value
