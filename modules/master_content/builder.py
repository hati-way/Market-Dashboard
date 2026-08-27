"""2단계: Master Content JSON 구조화.

MarketData 를 받아 새로운 MasterContent 를 만들고, 이를 파일로
저장/로드하는 기능을 제공한다. 이후 모든 파이프라인 단계는 이
MasterContent 를 계속 채워 나간다.
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.master_content.schema import MarketData, MasterContent

DEFAULT_MASTER_DIR = Path("data/master")


def build_master_content(topic: str, market_data: MarketData) -> MasterContent:
    """주제와 시장 데이터로부터 새 MasterContent 를 생성한다."""
    content = MasterContent()
    content.meta.topic = topic
    content.market_data = market_data
    return content


def save_master_content(content: MasterContent, directory: str | Path = DEFAULT_MASTER_DIR) -> Path:
    """MasterContent 를 data/master/<id>.json 으로 저장하고 경로를 반환한다."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{content.meta.id}.json"
    path.write_text(
        json.dumps(content.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_master_content(path: str | Path) -> MasterContent:
    """저장된 Master Content JSON 파일을 불러온다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return MasterContent.model_validate(raw)
