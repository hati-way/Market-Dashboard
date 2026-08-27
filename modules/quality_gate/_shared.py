"""score_*.py 들이 공유하는 텍스트 분석 헬퍼.

fact_validation.py 의 목록/heading 마커 제거 아이디어와 같은 패턴을
쓰지만, quality_gate는 wordpress_writer 내부 구현에 직접 의존하지
않도록 여기 따로 작은 버전을 둔다.
"""
from __future__ import annotations

import re

_HANGUL_RE = re.compile(r"[가-힣]")
_LEADING_MARKER_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+|#{1,3}\s+)")
_DEPENDENT_PREFIXES = ("위에서", "앞서", "이것은", "그것은", "이 수치는", "위 수치는")
_DEFINITION_PATTERN = re.compile(r"이란|란\s|는\s.{0,20}(뜻|의미)|\([^)]{2,20}\)")


def first_prose_block(markdown_text: str) -> str:
    """제목(#)/목록(-,*,1.) 마커가 아닌 첫 번째 문단(순수 텍스트)을 찾는다."""
    blocks = re.split(r"\n\s*\n", markdown_text.strip())
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        first_line = lines[0].strip()
        if first_line.startswith(("#", "-", "*")) or re.match(r"^\d+\.\s", first_line):
            remaining = lines[1:]
            if remaining and not remaining[0].strip().startswith(("#", "-", "*")):
                return " ".join(line.strip() for line in remaining)
            continue
        return " ".join(line.strip() for line in lines)
    return ""


def has_context_dependent_start(paragraph: str) -> bool:
    """"위에서 언급한", "앞서" 처럼 앞 문맥에 의존하는 표현으로 시작하는지."""
    return paragraph.strip().startswith(_DEPENDENT_PREFIXES)


def has_definition_style_sentence(markdown_text: str) -> bool:
    """"OO란", "OO(짧은 설명)" 같은 정의형 문장/괄호 설명이 있는지."""
    return bool(_DEFINITION_PATTERN.search(markdown_text))


def has_hangul(text: str) -> bool:
    return bool(_HANGUL_RE.search(text))


def keyword_repetition_ratio(text: str, keyword: str) -> float:
    """(키워드가 차지하는 글자수) / (전체 글자수)로 반복 과다를 근사한다.

    한국어는 공백 기준 단어 수가 부정확해서 단어 빈도 대신 글자수
    비중을 쓴다. 완벽하지 않지만 명백한 keyword stuffing은 잡아낸다.
    """
    if not keyword.strip():
        return 0.0
    plain = re.sub(r"<[^>]+>", " ", text)
    total_chars = max(len(plain), 1)
    occurrences = plain.lower().count(keyword.lower())
    return (occurrences * len(keyword)) / total_chars


def find_long_paragraphs(markdown_text: str, max_len: int) -> list[str]:
    """제목/목록이 아닌 문단 중 max_len자를 넘는 것들을 찾는다."""
    blocks = re.split(r"\n\s*\n", markdown_text.strip())
    long_blocks = []
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if first.startswith(("#", "-", "*")) or re.match(r"^\d+\.\s", first):
            continue
        paragraph = " ".join(line.strip() for line in lines)
        if len(paragraph) > max_len:
            long_blocks.append(paragraph)
    return long_blocks
