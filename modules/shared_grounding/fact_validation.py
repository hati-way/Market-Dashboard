"""Fact Grounding 검증(채널 공통, 일반화 버전).

원래 modules/wordpress_writer/fact_validation.py 안에 WordPressArticle
전용으로 구현되어 있던 로직을 텍스트+used_fact_ids만 받도록 일반화한
것이다(WordPressArticle이 실제로 쓰는 필드는 content_markdown과
used_fact_ids뿐이었다). wordpress_writer는 이제 이 모듈의
validate_text_grounding()을 그대로 호출하는 얇은 wrapper가 되었고,
threads_writer/notebooklm_script/youtube_meta/thumbnail_prompt도 각자의
본문 텍스트를 이 함수에 넘겨 동일한 검증을 재사용한다.

1. Fact ID 추적: 넘어온 used_fact_ids가 실제로
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

from .currency_scale import (
    ScaledAmount,
    classify_scaled_amount,
    find_scaled_amounts,
    scaled_amount_from_value_unit,
)


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
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_KOREAN_FULL_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
_KOREAN_MONTH_DAY_RE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")

# 목록(- , * , "1. ")과 heading(#, ##, ###) 마커를 줄 앞에서 제거해서,
# 목록 번호("1.", "2.")를 사실 숫자로 오인하지 않게 한다.
_LEADING_MARKER_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+|#{1,3}\s+)")

_PERCENT_UNIT_ALIASES = {"%", "percent", "퍼센트", "pct"}
_BP_UNIT_ALIASES = {"bp", "bps", "basis point", "basis points"}


def _strip_structural_markers(text: str) -> str:
    lines = [_LEADING_MARKER_RE.sub("", line) for line in text.splitlines()]
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


def _looks_like_it_has_concrete_facts(text: str) -> bool:
    stripped = _strip_structural_markers(text)
    if _PERCENT_RE.search(stripped) or _BP_RE.search(stripped):
        return True
    if find_scaled_amounts(stripped):
        return True
    full_dates, partial_dates = _find_dates(stripped)
    return bool(full_dates or partial_dates)


# ---- MasterContent에서 "허용된" 값 모으기 ----


def _add_with_unsigned_variant(allowed: set[str], value: object) -> None:
    """정규화한 값을 허용 목록에 넣고, 음수면 부호 없는 절대값도 함께 넣는다.

    _PERCENT_RE/_BP_RE(`\\d+(?:\\.\\d+)?`)는 "-" 부호를 애초에 캡처하지
    않으므로 본문에서 추출되는 값은 항상 부호 없는 절대값이다("하락했다"
    처럼 방향을 단어로 표현하거나, "-0.03%"처럼 명시적으로 부호를 써도
    정규식은 "0.03"만 잡는다). change_percent 등 MasterContent 쪽 값은
    부호가 있는 채로 저장되므로, 부호를 그대로 두면 음수인 실제 수치를
    본문에 정확히 옮겨 적어도 절대 매칭되지 않는다. 새로운 값을 허용하는
    게 아니라, 정규식이 원천적으로 부호를 비교할 수 없다는 사실에 맞춰
    비교 방식을 맞추는 것이다.
    """
    normalized = _normalize_decimal(value)
    allowed.add(normalized)
    if normalized.startswith("-"):
        allowed.add(normalized[1:])


def _collect_allowed_percents(content: MasterContent) -> set[str]:
    allowed: set[str] = set()
    for point in (
        *content.market_data.indices,
        *content.market_data.fx,
        *content.market_data.commodities,
    ):
        if point.change_percent is not None:
            _add_with_unsigned_variant(allowed, point.change_percent)
    for event in content.market_data.macro_events:
        for text in (event.actual, event.forecast, event.previous):
            if text:
                allowed.update(_normalize_decimal(m) for m in _PERCENT_RE.findall(text))
    for fact in content.analysis.facts:
        if fact.value is not None and fact.unit and fact.unit.strip().lower() in _PERCENT_UNIT_ALIASES:
            _add_with_unsigned_variant(allowed, fact.value)
    return allowed


def _collect_allowed_bps(content: MasterContent) -> set[str]:
    allowed: set[str] = set()
    for event in content.market_data.macro_events:
        for text in (event.actual, event.forecast, event.previous):
            if text:
                allowed.update(_normalize_decimal(m) for m in _BP_RE.findall(text))
    for fact in content.analysis.facts:
        if fact.value is not None and fact.unit and fact.unit.strip().lower() in _BP_UNIT_ALIASES:
            _add_with_unsigned_variant(allowed, fact.value)
    return allowed


def _collect_allowed_scaled_amounts(content: MasterContent) -> list[ScaledAmount]:
    """MasterContent 안에 실제로 존재하는 금액(만/억/조/million/billion/
    trillion 단위)들을 ScaledAmount 목록으로 모은다.

    facts(구조화된 value/unit)뿐 아니라 macro_events.actual/forecast/
    previous(자유 텍스트)도 함께 스캔한다.
    """
    allowed: list[ScaledAmount] = []
    for fact in content.analysis.facts:
        if fact.value is None or not fact.unit:
            continue
        amount = scaled_amount_from_value_unit(fact.value, fact.unit)
        if amount is not None:
            allowed.append(amount)
    for event in content.market_data.macro_events:
        for text in (event.actual, event.forecast, event.previous):
            if text:
                allowed.extend(find_scaled_amounts(text))
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


def _check_numeric_grounding(text: str, content: MasterContent) -> tuple[list[str], list[str]]:
    """text 안의 퍼센트/bp/금액/날짜가 MasterContent에 실제로 있는지 확인한다.

    반환값은 (근거 없는 항목 설명 목록, 통화가 불명확해 확인이 필요한
    항목 설명 목록)이다. 전자는 FAIL로 이어지고, 후자는 REVIEW_REQUIRED로
    이어진다(단정할 수 없는 것을 FAIL로 막지 않되, 그렇다고 조용히
    PASS시키지도 않는다).
    """
    stripped = _strip_structural_markers(text)
    unsupported: list[str] = []
    review_notes: list[str] = []

    allowed_percents = _collect_allowed_percents(content)
    for m in _PERCENT_RE.finditer(stripped):
        if _normalize_decimal(m.group(1)) not in allowed_percents:
            unsupported.append(f"{m.group(0).strip()} (MasterContent에 없는 퍼센트 수치)")

    allowed_bps = _collect_allowed_bps(content)
    for m in _BP_RE.finditer(stripped):
        if _normalize_decimal(m.group(1)) not in allowed_bps:
            unsupported.append(f"{m.group(0).strip()} (MasterContent에 없는 bp 수치)")

    allowed_amounts = _collect_allowed_scaled_amounts(content)
    for amount in find_scaled_amounts(stripped):
        classification = classify_scaled_amount(amount, allowed_amounts)
        if classification == "unsupported":
            unsupported.append(f"{amount.matched_text} (MasterContent에 없는 금액)")
        elif classification == "review":
            review_notes.append(
                f"{amount.matched_text} - 통화가 본문에 명시되지 않아 MasterContent 안의 "
                "여러 통화 중 무엇을 가리키는지 확인이 필요합니다."
            )

    allowed_dates = _collect_allowed_dates(content)
    full_dates, partial_dates = _find_dates(stripped)
    for found in full_dates:
        if found not in allowed_dates:
            unsupported.append(f"{found.isoformat()} (MasterContent에 없는 날짜)")
    for month, day in partial_dates:
        if not any(d.month == month and d.day == day for d in allowed_dates):
            unsupported.append(f"{month}월 {day}일 (MasterContent에 없는 날짜)")

    return unsupported, review_notes


def validate_text_grounding(
    text: str, used_fact_ids: list[str], content: MasterContent
) -> FactValidationResult:
    """생성된 텍스트(WordPress 본문, Threads 포스트 묶음, NotebookLM
    스크립트, YouTube 설명, 썸네일 문구 등 무엇이든)가 MasterContent에
    실제로 근거하는지 검증한다. 채널마다 문체/구조는 다르지만 이
    검증 로직 하나를 공통으로 쓴다.
    """
    fact_by_id: dict[str, Fact] = {fact.id: fact for fact in content.analysis.facts if fact.id}

    seen: set[str] = set()
    used: list[str] = []
    invalid_fact_ids: list[str] = []
    for fact_id in used_fact_ids:
        if fact_id in seen:
            continue
        seen.add(fact_id)
        if fact_id in fact_by_id:
            used.append(fact_id)
        else:
            invalid_fact_ids.append(fact_id)

    unsupported_claims: list[str] = [
        f"used_fact_ids에 존재하지 않는 Fact ID가 포함되어 있습니다: {fact_id}"
        for fact_id in invalid_fact_ids
    ]

    unsupported_numbers, currency_review_notes = _check_numeric_grounding(text, content)

    warnings: list[str] = list(currency_review_notes)
    if not used_fact_ids and _looks_like_it_has_concrete_facts(text):
        warnings.append(
            "used_fact_ids가 비어 있지만 본문에 구체적인 수치/날짜 표현이 있습니다. "
            "근거 Fact를 명시했는지 확인이 필요합니다."
        )

    for fact_id in used:
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
        used_fact_ids=used,
        invalid_fact_ids=invalid_fact_ids,
        unsupported_claims=unsupported_claims,
        unsupported_numbers=unsupported_numbers,
        warnings=warnings,
    )
