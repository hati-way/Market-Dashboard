"""GEO(Generative Engine Optimization) 검사.

생성형 AI가 이 글을 인용/요약할 때 신뢰할 수 있는 근거(수치, 날짜,
출처)가 충분한지를 점검한다. 지금은 시장 데이터가 최소 1개 이상
반영되어 있는지 정도의 규칙 기반 체크만 수행한다.
"""
from __future__ import annotations

import re

from modules.master_content.schema import MasterContent, QualityCheckResult


def check_geo(content: MasterContent) -> QualityCheckResult:
    html = content.wordpress.content_html
    issues: list[str] = []

    has_number = bool(re.search(r"\d", html))
    if not has_number:
        issues.append("본문에 구체적인 수치(데이터)가 포함되어 있지 않습니다.")

    if not content.market_data.as_of_date:
        issues.append("기준일(as_of_date)이 없어 데이터 시점을 특정할 수 없습니다.")

    return QualityCheckResult(passed=not issues, issues=issues)
