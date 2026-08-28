"""WordPress 타이포그래피 개선(CSS 스니펫) 관련 테스트.

WordPress 테마 파일은 건드리지 않았고, docs/wordpress_typography.css는
사용자가 WordPress 관리자에 직접 붙여넣는 정적 CSS 파일이다. 코드
테스트가 가능한 범위(파일 존재, 필수 selector/media query 포함 여부,
H1 중복 방지/제목 길이 경고가 여전히 동작하는지)만 확인한다. 기존
Quality Gate(modules/quality_gate)는 이번 라운드에서 변경하지 않았다.
"""
from pathlib import Path

from modules.quality_gate.seo_score import score_seo
from modules.wordpress_writer.markdown_html import markdown_to_html
from modules.wordpress_writer.models import WordPressArticle

CSS_PATH = Path("docs/wordpress_typography.css")


# ---- 4. CSS 파일 존재 ----


def test_typography_css_file_exists():
    assert CSS_PATH.exists()
    assert CSS_PATH.read_text(encoding="utf-8").strip()


# ---- 5. mobile media query 존재 ----


def test_typography_css_has_mobile_media_query():
    css = CSS_PATH.read_text(encoding="utf-8")
    assert "@media (max-width: 768px)" in css


# ---- 6. body text / H1 / H2 기본 selector 존재 ----


def test_typography_css_has_core_selectors():
    css = CSS_PATH.read_text(encoding="utf-8")
    for selector in (
        ".entry-title",
        ".wp-block-post-title",
        "article h1",
        "article h2",
        "article h3",
        "article p",
        "article ul",
        "article ol",
        "article a",
    ):
        assert selector in css, f"{selector} selector가 CSS에 없습니다."


def test_typography_css_minimizes_important_usage():
    css = CSS_PATH.read_text(encoding="utf-8")
    # 실제 선언부(예: "color: red !important;")에서는 쓰지 않는다.
    # 이 정책을 설명하는 주석 문구 자체에는 "!important"라는 단어가
    # 등장할 수 있으므로, 실제 선언 형태("!important;")만 센다.
    assert css.count("!important;") == 0


# ---- 1. content_html에 H1 중복 없음(기존 markdown_to_html 동작 재확인) ----


def test_markdown_to_html_never_produces_h1():
    html = markdown_to_html("# 제목\n\n## 소제목\n\n본문입니다.")
    assert "<h1" not in html.lower()
    assert "<h2>제목</h2>" in html
    assert "<h2>소제목</h2>" in html


# ---- 2. H2/H3 hierarchy 유지(기존 quality_gate 검사 재확인) ----


def test_seo_score_flags_h3_before_h2():
    article = WordPressArticle(
        title="적절한 길이의 제목입니다 테스트용",
        slug="test-slug",
        excerpt="e",
        meta_description="m" * 60,
        content_markdown="x",
        content_html="<h3>먼저 나온 h3</h3><h2>나중에 나온 h2</h2><p>본문</p>",
        primary_keyword="테스트",
    )

    result = score_seo(article)

    assert any("heading 순서" in issue for issue in result.issues)


# ---- 3. 너무 긴 title 경고 동작(기존 quality_gate 검사 재확인) ----


def test_seo_score_flags_overlong_title():
    overlong_title = (
        "미국 재무부 국채 바이백 300억 달러 확대 발표가 채권시장과 주식시장, "
        "달러 환율 전반에 걸쳐 어떤 장기적 파급 효과를 가져올 것인지에 대한 심층 분석과 전망"
    )
    article = WordPressArticle(
        title=overlong_title,
        slug="test-slug",
        excerpt="e",
        meta_description="m" * 60,
        content_markdown="x",
        content_html="<h2>x</h2><p>y</p>",
        primary_keyword="테스트",
    )

    result = score_seo(article)

    assert any("제목 길이" in rec for rec in result.recommendations)
