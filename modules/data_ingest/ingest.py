"""1단계: 금융/거시경제 데이터 입력.

지금은 "사람이 채운 JSON 파일" 또는 "dict" 를 읽어서 MarketData 로
검증하는 것까지만 담당한다. 추후 실시간 시세 API(예: 증권사 API,
FRED, Investing.com 등)를 붙일 때는 이 모듈 안에 fetch 함수를 추가하고,
그 결과를 동일하게 MarketData 로 변환해서 반환하면 된다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.master_content.schema import MarketData


def load_market_data_from_dict(raw: dict[str, Any]) -> MarketData:
    """dict 형태의 원본 데이터를 검증된 MarketData 로 변환한다."""
    return MarketData.model_validate(raw)


def load_market_data_from_json_file(path: str | Path) -> MarketData:
    """JSON 파일(data/input/*.json)을 읽어 MarketData 로 변환한다."""
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return load_market_data_from_dict(raw)
