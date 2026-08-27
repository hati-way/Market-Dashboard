"""NEO(네이버·한국어 콘텐츠) 점수.

fire-your-seo-agency의 references/neo-naver.md는 대부분 서치어드바이저
등록·웹마스터도구·블로그 투트랙 전략처럼 라이브 사이트/채널 운영이
전제인 내용이라(자세한 이유는
.claude/skills/fire-your-seo-agency/PROJECT_NOTES.md 참고), 그대로
가져올 수 있는 게 많지 않았다. 대신 이 파일은 작업 지시에 명시된
"한국어 콘텐츠 구조 검사" 항목(자연스러운 한국어, 번역체, 문단 길이,
전문용어 설명)을 직접 구현한다.

네이버 검색 알고리즘을 안다고 가정하지 않는다 — 여기 있는 규칙은
전부 "일반적으로 합의된 가독성/문체" 기준이지, 검증되지 않은 네이버
SEO 미신이 아니다.
"""
from __future__ import annotations

import re

from modules.master_content.schema import MasterContent
from modules.wordpress_writer.models import WordPressArticle

from ._shared import (
    find_long_paragraphs,
    first_prose_block,
    has_definition_style_sentence,
    has_hangul,
    keyword_repetition_ratio,
)
from .config import DEFAULT_CONFIG, QualityGateConfig
from .models import LaneScore

# "되어지다/되어진다" 류의 이중 피동. 잘 알려진 한국어 번역체(콩글리시) 패턴이라
# 검증되지 않은 미신이 아니라 통상적인 한국어 글쓰기 가이드에서 지적되는 표현이다.
_DOUBLE_PASSIVE_RE = re.compile(r"되어진|되어지다|되어졌|여겨지게\s?되")


def score_neo(
    article: WordPressArticle,
    content: MasterContent,
    config: QualityGateConfig = DEFAULT_CONFIG,
) -> LaneScore:
    score = 100
    issues: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    if article.title.strip() and not has_hangul(article.title):
        score -= 15
        issues.append("제목에 한국어가 없습니다.")

    topic = content.meta.topic.strip()
    first_block = first_prose_block(article.content_markdown)
    if topic and first_block:
        topic_tokens = [t for t in re.split(r"\s+", topic) if len(t) >= 2]
        if topic_tokens and not any(token in (article.title + first_block) for token in topic_tokens):
            warnings.append(
                "제목/본문 초반이 주제(meta.topic)와 뚜렷하게 연결되지 않을 수 있습니다. "
                "자동으로 판단하기 어려우니 직접 확인하세요."
            )

    if _DOUBLE_PASSIVE_RE.search(article.content_markdown):
        score -= 10
        recommendations.append(
            "이중 피동(예: '되어지다') 등 번역체 표현이 보입니다. "
            "자연스러운 능동/단순 표현으로 다듬는 것을 검토하세요."
        )

    ratio = keyword_repetition_ratio(article.content_markdown, article.primary_keyword)
    if ratio > config.max_keyword_repetition_ratio:
        score -= 15
        warnings.append(f"핵심 키워드 반복 비율이 과도합니다 ({ratio:.1%}).")

    long_paragraphs = find_long_paragraphs(article.content_markdown, config.max_paragraph_length)
    if long_paragraphs:
        score -= 10
        warnings.append(
            f"{config.max_paragraph_length}자를 넘는 문단이 {len(long_paragraphs)}개 있습니다. "
            "가독성을 위해 문단을 나누는 것을 검토하세요."
        )

    if not has_definition_style_sentence(article.content_markdown):
        recommendations.append(
            "한국 독자에게 낯설 수 있는 전문용어는 처음 등장할 때 짧게 풀어 "
            "설명하는 것을 검토하세요."
        )

    score = max(0, min(100, score))
    return LaneScore(score=score, issues=issues, warnings=warnings, recommendations=recommendations)
