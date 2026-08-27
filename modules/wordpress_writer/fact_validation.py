"""Fact Grounding 검증.

modules/wordpress_writer/generator.py 의 기존 "본문 안 소수점 숫자가
MasterContent에 있는지" 검사(HallucinationDetectedError)는 최소한의
방어선이었다. 이 모듈은 그 위에 두 가지를 더한다.

1. Fact ID 추적: WordPressArticle.used_fact_ids 가 실제로
   MasterContent.analysis.facts 에 존재하는 id만 가리키는지 확인한다.
2. 금융 콘텐츠에 흔한 숫자/단위/날짜(퍼센트, bp, 억/조/billion 등 규모
   표현, 날짜)를 더 구체적으로 뽑아내 MasterContent와 대조한다.

완벽한 자연어 사실검증을 목표로 하지 않는다. 목록/제목 번호처럼 사실이
아닌 숫자를 사실로 오인하지 않는 것과, 금융 콘텐츠에서 특히 위험한
숫자/단위/날짜 표현을 최대한 커버하는 것이 목표다.
"""
from __future__ import annotations

import re
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from modules.master_content.schema import ConfidenceLevel, Fact, MasterContent

from .models import WordPressArticle


class FactValidationStatus(str, Enum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAIL = "FAIL"


class FactValidationResult(BaseModel):
    status: FactValidationStatus
    used_fact_ids: list[str] = Field(default_factory=list)
    invalid_fact_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    unsupported_numbers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---- 숫자/단위/날짜 패턴 ----

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_BP_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:bps|bp|basis\s+points?)(?![a-zA-Z])", re.IGNORECASE
)
_DOLLAR_SCALE_RE = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(billion|million|trillion)\b", re.IGNORECASE
)
_KOREAN_SCALE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(억|조)\s*(?:달러|원)?")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_KOREAN_FULL_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
_KOREAN_MONTH_DAY_RE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")

# 목록(- , * , "1. ")과 heading(#, ##, ###) 마커를 줄 앞에서 제거해서,
# 목록 번호("1.", "2.")를 사실 숫자로 오인하지 않게 한다.
_LEADING_MARKER_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+|#{1,3}\s+)")

_PERCENT_UNIT_ALIASES = {"%", "percent", "퍼센트", "pct"}
_BP_UNIT_ALIASES = {"bp", "bps", "basis point", "basis points"}
_SCALE_UNIT_ALIASES = ("billion", "million", "trillion", "억", "조")


def _strip_structural_markers(markdown_text: str) -> str:
    lines = [_LEADING_MARKER_RE.sub("", line) for line in markdown_text.splitlines()]
    return "\n".join(lines)


def _normalize_decimal(value: object) -> str:
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _find_dates(text: str) -> tuple[list[date], list[tuple[int, int]]]:
    """본문에서 날짜를 찾는다.

    반환값은 (연도가 명시된 완전한 날짜 목록, (월, 일)만 있는 날짜 목록)
    이다. "2026년 9월 9일"처럼 완전한 날짜에 포함된 "9월 9일" 부분은
    중복으로 잡히지 않도록 span이 겹치면 제외한다.
    """
    full_dates: list[date] = []
    consumed_spans: list[tuple[int, int]] = []

    for pattern in (_ISO_DATE_RE, _KOREAN_FULL_DATE_RE):
        for m in pattern.finditer(text):
            year, month, day = (int(g) for g in m.groups())
            try:
                full_dates.append(date(year, month, day))
            except ValueError:
                continue
            consumed_spans.append(m.span())

    partial_dates: list[tuple[int, int]] = []
    for m in _KOREAN_MONTH_DAY_RE.finditer(text):
        span = m.span()
        if any(span[0] >= s and span[1] <= e for s, e in consumed_spans):
            continue
        month, day = (int(g) for g in m.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            partial_dates.append((month, day))

    return full_dates, partial_dates


def _looks_like_it_has_concrete_facts(markdown_text: str) -> bool:
    text = _strip_structural_markers(markdown_text)
    if _PERCENT_RE.search(text) or _BP_RE.search(text):
        return True
    if _DOLLAR_SCALE_RE.search(text) or _KOREAN_SCALE_RE.search(text):
        return True
    full_dates, partial_dates = _find_dates(text)
    return bool(full_dates or partial_dates)


# ---- MasterContent에서 "허용된" 값 모으기 ----


def _collect_allowed_percents(content: MasterContent) -> set[str]:
    allowed: set[str] = set()
    for point in (
        *content.market_data.indices,
        *content.market_data.fx,
        *content.market_data.commodities,
    ):
        if point.change_percent is not None:
            allowed.add(_normalize_decimal(point.change_percent))
    for event in content.market_data.macro_events:
        for text in (event.actual, event.forecast, event.previous):
            if text:
                allowed.update(_normalize_decimal(m) for m in _PERCENT_RE.findall(text))
    for fact in content.analysis.facts:
        if fact.value is not None and fact.unit and fact.unit.strip().lower() in _PERCENT_UNIT_ALIASES:
            allowed.add(_normalize_decimal(fact.value))
    return allowed


def _collect_allowed_bps(content: MasterContent) -> set[str]:
    allowed: set[str] = set()
    for event in content.market_data.macro_events:
        for text in (event.actual, event.forecast, event.previous):
            if text:
                allowed.update(_normalize_decimal(m) for m in _BP_RE.findall(text))
    for fact in content.analysis.facts:
        if fact.value is not None and fact.unit and fact.unit.strip().lower() in _BP_UNIT_ALIASES:
            allowed.add(_normalize_decimal(fact.value))
    return allowed


def _collect_allowed_currency_amounts(content: MasterContent) -> set[tuple[str, str]]:
    """(수치, 단위규모) 쌍의 집합. 예: ("4", "billion")."""
    allowed: set[tuple[str, str]] = set()
    for fact in content.analysis.facts:
        if fact.value is None or not fact.unit:
            continue
        unit_lower = fact.unit.lower()
        for scale in _SCALE_UNIT_ALIASES:
            if scale in unit_lower or scale in fact.unit:
                allowed.add((_normalize_decimal(fact.value), scale.lower()))
    return allowed


def _collect_allowed_dates(content: MasterContent) -> set[date]:
    allowed: set[date] = set()

    def add(value: object) -> None:
        if isinstance(value, date):
            allowed.add(value)
        elif isinstance(value, str) and value:
            try:
                allowed.add(date.fromisoformat(value[:10]))
            except ValueError:
                pass

    add(content.market_data.as_of_date)
    for event in content.market_data.macro_events:
        add(event.date)
    for fact in content.analysis.facts:
        if fact.date:
            allowed.add(fact.date)

    return allowed


# ---- 본문 검증 ----


def _check_numeric_grounding(content_markdown: str, content: MasterContent) -> list[str]:
    """content_markdown 안의 퍼센트/bp/금액/날짜가 MasterContent에 실제로
    있는지 확인하고, 근거 없는 항목의 설명 문자열 목록을 돌려준다.
    """
    text = _strip_structural_markers(content_markdown)
    unsupported: list[str] = []

    allowed_percents = _collect_allowed_percents(content)
    for m in _PERCENT_RE.finditer(text):
        if _normalize_decimal(m.group(1)) not in allowed_percents:
            unsupported.append(f"{m.group(0).strip()} (MasterContent에 없는 퍼센트 수치)")

    allowed_bps = _collect_allowed_bps(content)
    for m in _BP_RE.finditer(text):
        if _normalize_decimal(m.group(1)) not in allowed_bps:
            unsupported.append(f"{m.group(0).strip()} (MasterContent에 없는 bp 수치)")

    allowed_currency = _collect_allowed_currency_amounts(content)
    for m in _DOLLAR_SCALE_RE.finditer(text):
        key = (_normalize_decimal(m.group(1)), m.group(2).lower())
        if key not in allowed_currency:
            unsupported.append(f"{m.group(0).strip()} (MasterContent에 없는 금액)")
    for m in _KOREAN_SCALE_RE.finditer(text):
        key = (_normalize_decimal(m.group(1)), m.group(2).lower())
        if key not in allowed_currency:
            unsupported.append(f"{m.group(0).strip()} (MasterContent에 없는 금액)")

    allowed_dates = _collect_allowed_dates(content)
    full_dates, partial_dates = _find_dates(text)
    for found in full_dates:
        if found not in allowed_dates:
            unsupported.append(f"{found.isoformat()} (MasterContent에 없는 날짜)")
    for month, day in partial_dates:
        if not any(d.month == month and d.day == day for d in allowed_dates):
            unsupported.append(f"{month}월 {day}일 (MasterContent에 없는 날짜)")

    return unsupported


def validate_fact_grounding(article: WordPressArticle, content: MasterContent) -> FactValidationResult:
    """WordPressArticle이 MasterContent에 실제로 근거하는지 검증한다."""
    fact_by_id: dict[str, Fact] = {fact.id: fact for fact in content.analysis.facts if fact.id}

    seen: set[str] = set()
    used_fact_ids: list[str] = []
    invalid_fact_ids: list[str] = []
    for fact_id in article.used_fact_ids:
        if fact_id in seen:
            continue
        seen.add(fact_id)
        if fact_id in fact_by_id:
            used_fact_ids.append(fact_id)
        else:
            invalid_fact_ids.append(fact_id)

    unsupported_claims: list[str] = [
        f"used_fact_ids에 존재하지 않는 Fact ID가 포함되어 있습니다: {fact_id}"
        for fact_id in invalid_fact_ids
    ]

    unsupported_numbers = _check_numeric_grounding(article.content_markdown, content)

    warnings: list[str] = []
    if not article.used_fact_ids and _looks_like_it_has_concrete_facts(article.content_markdown):
        warnings.append(
            "used_fact_ids가 비어 있지만 본문에 구체적인 수치/날짜 표현이 있습니다. "
            "근거 Fact를 명시했는지 확인이 필요합니다."
        )

    for fact_id in used_fact_ids:
        fact = fact_by_id[fact_id]
        if fact.confidence == ConfidenceLevel.LOW:
            warnings.append(
                f"낮은 확신도(confidence=low)의 fact({fact_id})를 근거로 사용했습니다: {fact.claim}"
            )

    if invalid_fact_ids or unsupported_numbers:
        status = FactValidationStatus.FAIL
    elif warnings:
        status = FactValidationStatus.REVIEW_REQUIRED
    else:
        status = FactValidationStatus.PASS

    return FactValidationResult(
        status=status,
        used_fact_ids=used_fact_ids,
        invalid_fact_ids=invalid_fact_ids,
        unsupported_claims=unsupported_claims,
        unsupported_numbers=unsupported_numbers,
        warnings=warnings,
    )
