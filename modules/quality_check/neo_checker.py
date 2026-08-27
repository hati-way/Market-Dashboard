"""NEO 검사.

NEO의 정확한 정의는 팀/서비스마다 다를 수 있어(예: Naver 검색 최적화 등)
일단 "네이버를 포함한 국내 검색 환경에 대한 최적화"로 가정하고 최소한의
규칙(본문 길이, 문단 구성)만 체크한다. 실제 기준이 정해지면 이 파일의
규칙만 교체하면 된다.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, QualityCheckResult

CONTENT_MIN_LENGTH = 300


def check_neo(content: MasterContent) -> QualityCheckResult:
    html = content.wordpress.content_html
    issues: list[str] = []

    if len(html) < CONTENT_MIN_LENGTH:
        issues.append(f"본문 길이가 {CONTENT_MIN_LENGTH}자 미만입니다 (현재 {len(html)}자).")

    if html.count("<h2") + html.count("<h3") < 2:
        issues.append("문단 구성(소제목 2개 이상)이 부족합니다.")

    return QualityCheckResult(passed=not issues, issues=issues)
