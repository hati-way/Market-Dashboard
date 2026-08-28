"""1단계: 금융/거시경제 데이터 입력.

지금은 "사람이 채운 JSON 파일" 또는 "dict" 를 읽어서 MarketData 로
검증하는 것까지만 담당한다. 추후 실시간 시세 API(예: 증권사 API,
FRED, Investing.com 등)를 붙일 때는 이 모듈 안에 fetch 함수를 추가하고,
그 결과를 동일하게 MarketData 로 변환해서 반환하면 된다.

load_market_content_input_from_json_file() 은 market_data 만 담은
기존(flat) 형식과, market_data/analysis(+topic)를 함께 담은 확장
형식을 모두 지원한다. 실제 LLM으로 wordpress_writer를 돌릴 때는
analysis(facts/sources)가 없으면 LLM이 근거로 삼을 게 시세 숫자뿐이라
본문에서 숫자를 옮겨 적다가(반올림, 자릿수 누락 등) Fact Grounding
검증(HallucinationDetectedError)에 걸리기 쉽다 — 실제 LLM으로 시험할
땐 확장 형식으로 facts/sources를 명시적으로 채운 입력을 쓰는 것이
안전하다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

from modules.master_content.schema import Analysis, MarketData


def load_market_data_from_dict(raw: dict[str, Any]) -> MarketData:
    """dict 형태의 원본 데이터를 검증된 MarketData 로 변환한다."""
    return MarketData.model_validate(raw)


def load_market_data_from_json_file(path: str | Path) -> MarketData:
    """JSON 파일(data/input/*.json)을 읽어 MarketData 로 변환한다."""
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return load_market_data_from_dict(raw)


class MasterContentInput(NamedTuple):
    """load_market_content_input_from_json_file() 의 반환값."""

    topic: str | None
    market_data: MarketData
    analysis: Analysis


def load_market_content_input_from_json_file(path: str | Path) -> MasterContentInput:
    """market_data(필수) + topic/analysis(선택)를 함께 읽는다.

    두 가지 입력 형식을 지원한다.

    1. 기존(flat) 형식 — JSON 최상위가 그대로 MarketData 필드
       (as_of_date/indices/fx/... 등). "market_data"/"analysis" 키가
       없으면 이 형식으로 간주하고, topic=None, analysis=빈 Analysis()
       를 돌려준다. 기존 샘플 파일(data/input/sample_market_data.json)
       은 계속 이 형식으로 그대로 동작한다.
    2. 확장 형식 — {"topic": "...", "market_data": {...}, "analysis": {...}}
       처럼 세 키를 최상위에 둔다. "market_data"/"analysis" 중 하나라도
       있으면 이 형식으로 간주한다. topic/analysis는 생략 가능(생략 시
       각각 None / 빈 Analysis()).
    """
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))

    if "market_data" in raw or "analysis" in raw:
        market_data = MarketData.model_validate(raw.get("market_data") or {})
        analysis = Analysis.model_validate(raw.get("analysis") or {})
        topic = raw.get("topic") or None
        return MasterContentInput(topic=topic, market_data=market_data, analysis=analysis)

    return MasterContentInput(topic=None, market_data=load_market_data_from_dict(raw), analysis=Analysis())
