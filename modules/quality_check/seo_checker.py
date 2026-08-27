"""SEO(검색엔진 최적화) 검사.

지금은 규칙 기반의 최소한의 체크만 수행한다. 필요에 따라 검사 항목을
자유롭게 추가하면 된다.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, QualityCheckResult

TITLE_MIN, TITLE_MAX = 10, 70
META_DESC_MIN, META_DESC_MAX = 50, 160


def check_seo(content: MasterContent) -> QualityCheckResult:
    wp = content.wordpress
    issues: list[str] = []

    if not (TITLE_MIN <= len(wp.title) <= TITLE_MAX):
        issues.append(f"제목 길이는 {TITLE_MIN}~{TITLE_MAX}자를 권장합니다 (현재 {len(wp.title)}자).")

    if not (META_DESC_MIN <= len(wp.seo.meta_description) <= META_DESC_MAX):
        issues.append(
            f"메타 설명 길이는 {META_DESC_MIN}~{META_DESC_MAX}자를 권장합니다 "
            f"(현재 {len(wp.seo.meta_description)}자)."
        )

    if wp.seo.focus_keyword and wp.seo.focus_keyword not in wp.title:
        issues.append("핵심 키워드가 제목에 포함되어 있지 않습니다.")

    if not wp.content_html.strip():
        issues.append("본문이 비어 있습니다.")

    return QualityCheckResult(passed=not issues, issues=issues)
