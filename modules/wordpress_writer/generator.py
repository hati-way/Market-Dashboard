"""3단계: WordPress 분석글 생성.

지금은 LLM 없이도 파이프라인 전체가 동작하는 것을 확인할 수 있도록
market_data 를 간단한 템플릿으로 조립한 초안(placeholder)을 만든다.

TODO: clients/llm_client.py 가 실제 OpenAI/Anthropic 연동을 갖추면,
      아래 _build_placeholder_html() 대신 LLM 호출 결과를 사용하도록
      교체한다. MasterContent 를 받아 MasterContent 를 반환하는
      함수 시그니처(generate_wordpress_content)는 그대로 유지한다.
"""
from __future__ import annotations

from modules.master_content.schema import MasterContent, SeoMeta, WordPressContent


def _build_placeholder_html(content: MasterContent) -> str:
    md = content.market_data
    lines = [f"<h2>{content.meta.topic or '시장 브리핑'}</h2>"]
    lines.append(f"<p>기준일: {md.as_of_date}</p>")

    if md.indices:
        lines.append("<h3>주요 지수</h3><ul>")
        for item in md.indices:
            lines.append(f"<li>{item.name}: {item.value} ({item.change_percent}%)</li>")
        lines.append("</ul>")

    if md.fx:
        lines.append("<h3>환율</h3><ul>")
        for item in md.fx:
            lines.append(f"<li>{item.name}: {item.value}</li>")
        lines.append("</ul>")

    if md.macro_events:
        lines.append("<h3>주요 이벤트</h3><ul>")
        for ev in md.macro_events:
            lines.append(f"<li>{ev.date} {ev.name} (예상: {ev.forecast})</li>")
        lines.append("</ul>")

    return "\n".join(lines)


def generate_wordpress_content(content: MasterContent) -> MasterContent:
    """MasterContent.market_data 를 바탕으로 wordpress 필드를 채운다."""
    topic = content.meta.topic or "시장 브리핑"

    content.wordpress = WordPressContent(
        title=f"{content.market_data.as_of_date} {topic}",
        slug="",
        excerpt=f"{topic} 관련 {content.market_data.as_of_date} 시황 요약.",
        content_html=_build_placeholder_html(content),
        tags=[],
        categories=[],
        seo=SeoMeta(
            meta_title=f"{content.market_data.as_of_date} {topic}",
            meta_description=f"{topic} 관련 {content.market_data.as_of_date} 시황 요약.",
            focus_keyword=topic,
        ),
    )
    content.touch()
    return content
