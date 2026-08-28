"""NotebookLM 영상 원고 생성기(LLM)의 구조화된 출력 스키마."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotebookLmScriptOutput(BaseModel):
    title: str
    hook: str
    script: str
    # 영상의 각 구간 제목(9개 구조: Hook/사건 설명/개념 설명/전달경로/
    # 채권시장/주식시장/반대 시나리오/앞으로 볼 지표/결론). 타임스탬프는
    # 아직 녹음 전이라 없다 - 실제 영상 제작 후에나 알 수 있는 값이므로
    # 시스템이 임의로 만들지 않는다.
    chapters: list[str]
    used_fact_ids: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now_iso)

    @field_validator("script")
    @classmethod
    def _validate_script_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("script가 비어 있습니다.")
        return value

    @field_validator("chapters")
    @classmethod
    def _validate_chapters_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("chapters가 비어 있습니다.")
        return value
