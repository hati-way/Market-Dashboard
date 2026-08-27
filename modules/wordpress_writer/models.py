"""WordPress 글 생성기(LLM)의 구조화된 출력 스키마.

LLM의 자유형 텍스트 응답을 그대로 저장하지 않고, 이 모델로 파싱/검증한
뒤에만 MasterContent.wordpress 에 반영한다.

content_html 과 source_list 는 LLM이 응답에 포함하더라도 신뢰하지
않는다: content_html은 항상 content_markdown으로부터 시스템이 직접
변환하고, source_list는 항상 MasterContent.analysis.sources/facts 에서
시스템이 직접 만든다 (LLM이 출처를 지어내는 것을 막기 위함).
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WordPressArticle(BaseModel):
    title: str
    slug: str
    excerpt: str
    meta_description: str
    content_markdown: str
    primary_keyword: str
    related_keywords: list[str] = Field(default_factory=list)

    # LLM이 본문 작성에 근거로 사용한 MasterContent.analysis.facts의 id 목록
    # (예: ["fact_001", "fact_003"]). LLM이 보낸 값 그대로를 신뢰하지 않고,
    # fact_validation.validate_fact_grounding()이 실제 존재하는 id인지
    # 검증한 뒤에만 사용한다.
    used_fact_ids: list[str] = Field(default_factory=list)

    # 아래 두 필드는 LLM 응답에 값이 있어도 무시되고, 시스템이 직접 채운다.
    content_html: str = ""
    source_list: list[str] = Field(default_factory=list)

    generated_at: str = Field(default_factory=_now_iso)
