"""SEO 점수.

fire-your-seo-agency의 references/seo.md 중 "제목/설명 길이",
"페이지마다 고유한 메타", "구조화 데이터는 가시 텍스트와 100% 일치"
같은, 우리가 지금 만드는 단일 글에 적용 가능한 원칙만 가져왔다.
사이트맵·canonical·hreflang·이미지 최적화처럼 라이브 사이트 운영이
전제인 항목은 이번 단계에서 검사하지 않는다(자세한 이유는
.claude/skills/fire-your-seo-agency/PROJECT_NOTES.md 참고).

점수를 올리려고 키워드를 억지로 반복시키는 방향의 규칙은 넣지 않는다 —
오히려 반복이 과하면 감점한다.
"""
from __future__ import annotations

import re

from modules.wordpress_writer.models import WordPressArticle

from ._shared import keyword_repetition_ratio
from .config import DEFAULT_CONFIG, QualityGateConfig
from .models import LaneScore

_H1_RE = re.compile(r"<h1\b", re.IGNORECASE)
_H2_RE = re.compile(r"<h2\b", re.IGNORECASE)
_H3_RE = re.compile(r"<h3\b", re.IGNORECASE)
_LINK_RE = re.compile(r"<a\s", re.IGNORECASE)


def _heading_hierarchy_violation(html_text: str) -> bool:
    first_h2 = html_text.find("<h2")
    first_h3 = html_text.find("<h3")
    if first_h3 == -1:
        return False
    if first_h2 == -1:
        return True  # h3만 있고 h2가 없다
    return first_h3 < first_h2


def score_seo(article: WordPressArticle, config: QualityGateConfig = DEFAULT_CONFIG) -> LaneScore:
    score = 100
    issues: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    title = article.title.strip()
    if title and not (config.title_min_len <= len(title) <= config.title_max_len):
        score -= 15
        recommendations.append(
            f"제목 길이를 {config.title_min_len}~{config.title_max_len}자로 조정하는 것을 "
            f"검토하세요 (현재 {len(title)}자)."
        )

    slug = article.slug.strip()
    if not slug:
        score -= 10
        recommendations.append("slug가 비어 있습니다.")
    elif len(slug) > config.slug_max_len:
        score -= 5
        recommendations.append(f"slug가 {config.slug_max_len}자를 넘습니다 (현재 {len(slug)}자).")

    meta_desc = article.meta_description.strip()
    if not (config.meta_description_min_len <= len(meta_desc) <= config.meta_description_max_len):
        score -= 15
        recommendations.append(
            f"meta description 길이를 {config.meta_description_min_len}~"
            f"{config.meta_description_max_len}자로 조정하는 것을 검토하세요 "
            f"(현재 {len(meta_desc)}자)."
        )

    html_text = article.content_html or ""

    # H1은 title 필드 하나가 맡는다(WordPress가 글 제목을 h1으로 렌더링하는
    # 것을 전제). 본문 안에 별도의 h1이 있으면 중복이다.
    if _H1_RE.search(html_text):
        score -= 20
        issues.append("본문 안에 h1 태그가 있습니다. 제목(title)만 h1 역할을 해야 합니다.")

    if not (_H2_RE.search(html_text) or _H3_RE.search(html_text)):
        score -= 15
        recommendations.append("본문에 h2/h3 소제목이 없습니다.")
    elif _heading_hierarchy_violation(html_text):
        score -= 10
        issues.append("heading 순서가 올바르지 않습니다 (h2 없이 h3가 먼저 나옵니다).")

    if not _LINK_RE.search(html_text):
        score -= 10
        recommendations.append("본문에 링크(출처/내부 링크)가 없습니다.")

    # canonical: 아직 실제 발행 URL이 없으므로, 나중에 canonical을 구성할 수
    # 있는 최소 조건(slug 존재)만 확인한다. 실제 canonical 태그 생성은
    # wordpress_publisher 구현 이후의 일이다.
    if not slug:
        recommendations.append("slug가 없으면 나중에 canonical URL을 구성할 수 없습니다.")

    ratio = keyword_repetition_ratio(html_text or article.content_markdown, article.primary_keyword)
    if ratio > config.max_keyword_repetition_ratio:
        score -= 20
        warnings.append(f"핵심 키워드 '{article.primary_keyword}' 반복 비율이 과도합니다 ({ratio:.1%}).")

    score = max(0, min(100, score))
    return LaneScore(score=score, issues=issues, warnings=warnings, recommendations=recommendations)
