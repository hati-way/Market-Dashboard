"""Threads 글 생성기(LLM)의 구조화된 출력 스키마.

LLM의 자유형 텍스트 응답을 그대로 저장하지 않고, 이 모델로 파싱/검증한
뒤에만 MasterContent.threads 에 반영한다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

MIN_POSTS = 3
MAX_POSTS = 5
DEFAULT_POST_COUNT = 4
MAX_POST_LENGTH = 400

# 각 post는 "1/4 "처럼 "현재번호/전체개수 " 형태로 시작해야 한다.
_POST_NUMBER_RE = re.compile(r"^(\d+)/(\d+)\s")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ThreadsOutput(BaseModel):
    posts: list[str]
    hook: str
    key_message: str

    # LLM이 근거로 사용한 MasterContent.analysis.facts의 id 목록. LLM이
    # 보낸 값을 그대로 신뢰하지 않고, validate_text_grounding()이 실제
    # 존재하는 id인지 검증한 뒤에만 사용한다(wordpress_writer와 동일한
    # 원칙).
    used_fact_ids: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now_iso)

    @field_validator("posts")
    @classmethod
    def _validate_posts(cls, value: list[str]) -> list[str]:
        if not (MIN_POSTS <= len(value) <= MAX_POSTS):
            raise ValueError(
                f"posts는 {MIN_POSTS}~{MAX_POSTS}개여야 합니다(현재 {len(value)}개)."
            )
        for i, post in enumerate(value, start=1):
            if not post.strip():
                raise ValueError(f"{i}번째 post가 비어 있습니다.")
            if len(post) > MAX_POST_LENGTH:
                raise ValueError(
                    f"{i}번째 post가 {MAX_POST_LENGTH}자를 넘습니다(현재 {len(post)}자)."
                )
        return value

    @model_validator(mode="after")
    def _validate_post_numbering(self) -> "ThreadsOutput":
        """각 post가 "1/4 ", "2/4 "처럼 실제 전체 개수와 맞는 번호로
        시작하는지 확인한다(개수 검증과 달리 post 개수 자체가 있어야
        전체 개수를 알 수 있어 field_validator가 아닌 model_validator로
        확인한다).
        """
        total = len(self.posts)
        for i, post in enumerate(self.posts, start=1):
            match = _POST_NUMBER_RE.match(post)
            expected = f"{i}/{total}"
            actual = f"{match.group(1)}/{match.group(2)}" if match else None
            if actual != expected:
                raise ValueError(
                    f"{i}번째 post는 \"{expected} \"로 시작해야 합니다"
                    f"(현재 시작 부분: {post[:20]!r})."
                )
        return self
