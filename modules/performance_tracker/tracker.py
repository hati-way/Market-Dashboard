"""10단계: 발행 후 성과 데이터 기록 (Search Console 등).

지금은 임의의 지표 dict 를 받아 MasterContent.performance 리스트에
추가하는 것까지만 담당한다.
TODO: clients/search_console_client.py 가 구현되면, 그 결과를 이
      함수로 넘겨 자동으로 기록하도록 pipeline/orchestrator.py 에서
      호출한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from modules.master_content.schema import MasterContent, PerformanceRecord


def add_performance_record(
    content: MasterContent, source: str, metrics: dict
) -> MasterContent:
    record = PerformanceRecord(
        recorded_at=datetime.now(timezone.utc).isoformat(),
        source=source,
        metrics=metrics,
    )
    content.performance.append(record)
    content.touch()
    return content
