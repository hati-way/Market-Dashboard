"""아주 제한적인 마크다운 -> HTML 변환기.

LLM이 생성한 마크다운 본문을 WordPress에 넣을 수 있는 HTML로 바꾼다.
지원하는 문법만 명시적으로 HTML 태그로 바꾸고, 그 외 모든 텍스트는
html.escape로 이스케이프한다. 따라서 LLM 응답 본문에 임의의 HTML/스크립트
태그가 섞여 있어도 그대로 렌더링되지 않는다("안전하지 않은 임의 HTML
삽입 금지").

지원 문법: h2(##)/h3(###)/h1(#, h2로 취급), 문단, 순서 없는/있는 목록
(-,* / 1.), 인용(>), 표(|...|), **굵게**, [텍스트](https://...) 링크.
그 외 문법(이미지, 코드블록, 중첩 목록 등)은 지원하지 않는다.
"""
from __future__ import annotations

import html
import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_UL_ITEM_RE = re.compile(r"^[-*]\s+(.*)$")
_OL_ITEM_RE = re.compile(r"^\d+\.\s+(.*)$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def _render_inline(text: str) -> str:
    # 먼저 모든 텍스트를 이스케이프한 뒤, 우리가 인식하는 문법만 다시
    # 실제 태그로 바꾼다. 그래서 원본에 <script> 같은 태그가 있어도
    # &lt;script&gt; 로 남아 실행되지 않는다.
    escaped = html.escape(text.strip(), quote=False)
    escaped = _LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}" rel="nofollow noopener" target="_blank">{m.group(1)}</a>',
        escaped,
    )
    escaped = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    return escaped


def _split_table_row(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _render_table(lines: list[str]) -> str:
    header_cells = _split_table_row(lines[0])
    body_lines = lines[1:]
    if body_lines and _TABLE_SEPARATOR_RE.match(body_lines[0].strip()):
        body_lines = body_lines[1:]

    thead = "".join(f"<th>{_render_inline(c)}</th>" for c in header_cells)
    rows = []
    for line in body_lines:
        cells = _split_table_row(line)
        rows.append("<tr>" + "".join(f"<td>{_render_inline(c)}</td>" for c in cells) + "</tr>")

    return f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def markdown_to_html(markdown_text: str) -> str:
    if not markdown_text or not markdown_text.strip():
        return ""

    blocks = re.split(r"\n\s*\n", markdown_text.strip())
    rendered: list[str] = []

    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        # 제목(#/##/###)은 한 줄만 소비한다. 같은 블록 안에 제목 다음 줄로
        # 본문이 바로 이어져도(빈 줄로 구분되지 않아도) 그 본문을 잃지
        # 않도록, 나머지 줄은 아래에서 별도 블록처럼 계속 판별한다.
        if lines[0].startswith("### "):
            rendered.append(f"<h3>{_render_inline(lines[0][4:])}</h3>")
            lines = lines[1:]
        elif lines[0].startswith("## "):
            rendered.append(f"<h2>{_render_inline(lines[0][3:])}</h2>")
            lines = lines[1:]
        elif lines[0].startswith("# "):
            rendered.append(f"<h2>{_render_inline(lines[0][2:])}</h2>")
            lines = lines[1:]

        if not lines:
            continue

        if all(line.strip().startswith(">") for line in lines):
            inner = " ".join(_render_inline(line.strip().lstrip(">").strip()) for line in lines)
            rendered.append(f"<blockquote><p>{inner}</p></blockquote>")
        elif all(_UL_ITEM_RE.match(line.strip()) for line in lines):
            items = "".join(
                f"<li>{_render_inline(_UL_ITEM_RE.match(line.strip()).group(1))}</li>"
                for line in lines
            )
            rendered.append(f"<ul>{items}</ul>")
        elif all(_OL_ITEM_RE.match(line.strip()) for line in lines):
            items = "".join(
                f"<li>{_render_inline(_OL_ITEM_RE.match(line.strip()).group(1))}</li>"
                for line in lines
            )
            rendered.append(f"<ol>{items}</ol>")
        elif len(lines) >= 2 and all(line.strip().startswith("|") for line in lines):
            rendered.append(_render_table(lines))
        else:
            paragraph = " ".join(line.strip() for line in lines)
            rendered.append(f"<p>{_render_inline(paragraph)}</p>")

    return "\n".join(rendered)
