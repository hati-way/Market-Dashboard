"""AEO(Answer Engine Optimization) 점수.

fire-your-seo-agency의 references/aeo.md 중 "첫 문단 직답(40자 내외)",
"문장이 맥락 의존적이지 않게", "기준·날짜 명시", "표로 구조화" 원칙을
가져왔다. FAQ 블록/FAQPage JSON-LD는 명시적으로 가져오지 않았다 —
글 전체를 FAQ 형식으로 바꾸지 않는다는 이번 작업 지시와 맞지 않기
때문이다(자세한 이유는
.claude/skills/fire-your-seo-agency/PROJECT_NOTES.md 참고).
"""
from __future__ import annotations

import re

from modules.master_content.schema import MasterContent
from modules.wordpress_writer.models import WordPressArticle

from ._shared import first_prose_block, has_context_dependent_start, has_definition_style_sentence
from .config import DEFAULT_CONFIG, QualityGateConfig
from .models import LaneScore

_FIGURE_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*(?:bp|bps)\b", re.IGNORECASE)


def _mentions_many_figures_without_structure(markdown_text: str, html_text: str) -> bool:
    figure_count = len(_FIGURE_RE.findall(markdown_text))
    has_structure = any(tag in (html_text or "") for tag in ("<ul", "<ol", "<table"))
    return figure_count >= 3 and not has_structure


def score_aeo(
    article: WordPressArticle,
    content: MasterContent,
    config: QualityGateConfig = DEFAULT_CONFIG,
) -> LaneScore:
    score = 100
    issues: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    first_answer = first_prose_block(article.content_markdown)
    if not first_answer:
        score -= 30
        issues.append("글 초반에 질문에 대한 직접 답변으로 보이는 문단이 없습니다.")
    else:
        if len(first_answer) > config.direct_answer_max_len:
            score -= 10
            recommendations.append(
                f"핵심 답변 문단이 {config.direct_answer_max_len}자보다 깁니다 "
                f"(현재 {len(first_answer)}자). 더 짧고 직접적인 결론 문장으로 "
                "시작하는 것을 검토하세요."
            )
        if has_context_dependent_start(first_answer):
            score -= 10
            issues.append(
                "첫 답변 문단이 앞 문맥에 의존하는 표현으로 시작해 독립적으로 "
                "인용하기 어렵습니다."
            )

    primary_question = content.analysis.primary_question.strip()
    if primary_question and first_answer:
        question_tokens = [t for t in re.split(r"\s+", primary_question) if len(t) >= 2]
        combined = f"{article.title} {first_answer}"
        if question_tokens and not any(token in combined for token in question_tokens):
            warnings.append(
                "질문(analysis.primary_question)과 첫 답변 문단의 연결이 뚜렷하지 "
                "않을 수 있습니다. 자동으로 판단하기 어려우니 직접 확인하세요."
            )

    if not has_definition_style_sentence(article.content_markdown):
        recommendations.append("전문용어를 처음 등장시킬 때 짧게 정의하는 문장을 추가하는 것을 검토하세요.")

    if _mentions_many_figures_without_structure(article.content_markdown, article.content_html):
        score -= 10
        warnings.append("수치가 여러 개 언급되지만 표/목록으로 구조화되지 않았습니다.")

    score = max(0, min(100, score))
    return LaneScore(score=score, issues=issues, warnings=warnings, recommendations=recommendations)
