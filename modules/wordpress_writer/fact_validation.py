"""Fact Grounding 검증(WordPress 전용 얇은 wrapper).

실제 검증 로직은 modules.shared_grounding.fact_validation으로
일반화되어 threads_writer/notebooklm_script/youtube_meta/thumbnail_prompt
에서도 재사용된다. 이 모듈은 기존 호출부(WordPressArticle을 그대로
넘기는 코드 - generator.py, quality_gate/*, tests/*)와의 하위 호환을
위한 wrapper이며, WordPressArticle이 실제로 쓰는 필드(content_markdown,
used_fact_ids)만 shared_grounding.validate_text_grounding에 그대로
넘긴다. 동작/판정 기준은 이전과 완전히 동일하다(로직을 옮기기만 했다).
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent
from modules.shared_grounding.fact_validation import (
    FactValidationResult,
    FactValidationStatus,
    validate_text_grounding,
)

from .models import WordPressArticle

__all__ = [
    "FactValidationResult",
    "FactValidationStatus",
    "validate_fact_grounding",
    "validate_text_grounding",
]


def validate_fact_grounding(article: WordPressArticle, content: MasterContent) -> FactValidationResult:
    """WordPressArticle이 MasterContent에 실제로 근거하는지 검증한다."""
    return validate_text_grounding(article.content_markdown, article.used_fact_ids, content)
