"""LLM 구조화 출력 파싱 + 최소 수준 환각(숫자) 방지 검사(채널 공통).

modules/wordpress_writer/generator.py의 "1차 방어선"
(_check_for_hallucinated_numbers)과 동일한 원칙을 threads_writer/
notebooklm_script/youtube_meta/thumbnail_prompt가 각자 구현을 복제하지
않고 재사용할 수 있도록 일반화한 것이다. wordpress_writer.generator는
이번 라운드에서 건드리지 않았으므로(기존 WordPress 로직 유지) 그
파일의 private 구현은 그대로 남아 있고, 이 모듈이 별도의 공용
구현이다 - 두 구현이 하는 일은 같지만(텍스트 안 소수점 숫자를
MasterContent 값과 대조) wordpress_writer 쪽은 손대지 않는다는 제약
때문에 물리적으로는 분리되어 있다.
"""
from __future__ import annotations

import json
import re

from modules.master_content.schema import MasterContent

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_DECIMAL_NUMBER_RE = re.compile(r"\d+\.\d+")


class GenerationParsingError(Exception):
    """LLM 응답을 JSON으로 파싱하거나 구조화 모델로 검증하지 못했을 때 발생한다."""


class HallucinationDetectedError(Exception):
    """MasterContent에 없는 소수점 숫자가 생성된 텍스트에 포함된 경우 발생한다.

    완전한 사실 검증이 아니라 "명백히 근거 없는 정밀 수치"를 걸러내기
    위한 최소 장치다. 퍼센트/bp/금액/날짜/Fact ID까지 구조적으로
    대조하는 더 엄격한 검사는
    modules.shared_grounding.fact_validation.validate_text_grounding이
    본다.
    """


def extract_json_text(raw: str) -> str:
    match = _JSON_BLOCK_RE.search(raw)
    return match.group(1) if match else raw.strip()


def parse_llm_json(raw: str) -> dict:
    json_text = extract_json_text(raw)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise GenerationParsingError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {exc}") from exc
    if not isinstance(data, dict):
        raise GenerationParsingError("LLM 응답 JSON이 객체(object) 형태가 아닙니다.")
    return data


def _normalize_number(value: object) -> str | None:
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return None


def _collect_allowed_numbers(content: MasterContent) -> set[str]:
    """텍스트에 등장해도 되는(=MasterContent에 실제로 존재하는) 소수점 숫자 집합.

    음수 값(예: change_percent=-0.03)은 절대값도 함께 넣는다 - 정규식이
    "-" 부호를 캡처하지 못해 본문에서 추출되는 값은 항상 부호 없는
    절대값이기 때문이다(modules/wordpress_writer/generator.py의
    _collect_allowed_numbers와 동일한 이유).
    """
    numbers: set[str] = set()

    def add(value: object) -> None:
        normalized = _normalize_number(value)
        if normalized is not None:
            numbers.add(normalized)
            if normalized.startswith("-"):
                numbers.add(normalized[1:])

    for point in (
        *content.market_data.indices,
        *content.market_data.fx,
        *content.market_data.commodities,
    ):
        add(point.value)
        add(point.change_percent)

    for event in content.market_data.macro_events:
        for text in (event.actual, event.forecast, event.previous):
            if text:
                for match in _DECIMAL_NUMBER_RE.findall(text):
                    add(match)

    for fact in content.analysis.facts:
        add(fact.value)

    return numbers


def check_for_hallucinated_numbers(text: str, content: MasterContent) -> None:
    """text 안의 소수점 숫자가 MasterContent에 실제로 존재하는지 확인하는
    최소 수준의 환각 방지 검증이다. 근거 없는 값이 있으면
    HallucinationDetectedError를 던진다.
    """
    allowed = _collect_allowed_numbers(content)
    found = {
        normalized
        for raw_number in _DECIMAL_NUMBER_RE.findall(text)
        if (normalized := _normalize_number(raw_number)) is not None
    }
    unknown = found - allowed
    if unknown:
        raise HallucinationDetectedError(
            "MasterContent에 없는 수치가 생성된 텍스트에 포함되어 있습니다: "
            + ", ".join(sorted(unknown))
        )
