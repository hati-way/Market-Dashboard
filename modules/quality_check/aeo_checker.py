"""AEO(Answer Engine Optimization) 검사.

ChatGPT/Perplexity 같은 답변형 엔진이 이 글에서 바로 답을 인용해갈 수
있는지를 점검한다. 지금은 "글 구조(소제목)가 있는지", "핵심 요약이
앞부분에 있는지" 정도의 규칙 기반 체크만 수행한다.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, QualityCheckResult


def check_aeo(content: MasterContent) -> QualityCheckResult:
    html = content.wordpress.content_html
    issues: list[str] = []

    if "<h2" not in html and "<h3" not in html:
        issues.append("소제목(h2/h3)이 없어 답변 엔진이 구조를 파악하기 어렵습니다.")

    if not content.wordpress.excerpt.strip():
        issues.append("요약(excerpt)이 없어 핵심 답변을 바로 제공하기 어렵습니다.")

    return QualityCheckResult(passed=not issues, issues=issues)
