"""3단계: WordPress 분석글 생성 (Anthropic Claude 기반).

MasterContent.market_data 와 MasterContent.analysis 를 유일한 사실
근거로 삼아 LLM에게 WordPress 글을 구조화된 JSON으로 생성하도록
요청한다.

- LLM 응답은 자유형 텍스트를 그대로 저장하지 않고 WordPressArticle
  스키마로 파싱/검증한다. 파싱/검증에 실패하면 명확한 예외를 내고,
  잘못된 글을 MasterContent.wordpress 에 반영하지 않는다.
- content_html 은 LLM이 준 값을 신뢰하지 않고, content_markdown을
  markdown_html.markdown_to_html() 로 시스템이 직접 변환한다.
- source_list 는 LLM이 준 값을 신뢰하지 않고, MasterContent.analysis의
  sources/facts 에서 시스템이 직접 만든다.
- 본문에 등장하는 소수점 숫자가 MasterContent 안에 실제로 존재하는지
  최소한으로 검증해서(환각 방지) 없는 숫자가 있으면 예외를 낸다.
"""
from __future__ import annotations

import html
import json
import re

from pydantic import ValidationError

from clients.llm_client import LlmClient
from modules.master_content.schema import MasterContent, SeoMeta, WordPressContent

from .fact_validation import FactValidationResult, FactValidationStatus, validate_fact_grounding
from .markdown_html import markdown_to_html
from .models import WordPressArticle

DEFAULT_ARTICLE_MAX_TOKENS = 4096


class WordPressGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


class HallucinationDetectedError(WordPressGenerationError):
    """MasterContent에 없는 수치가 생성된 본문에 포함된 경우 발생한다.

    본문 안 소수점 숫자를 MasterContent 값과 단순 대조하는 최소한의
    검사다(_check_for_hallucinated_numbers). 퍼센트/bp/금액/날짜와 Fact ID
    까지 구조적으로 대조하는 더 엄격한 검사는 FactGroundingError를 본다.
    """


class FactGroundingError(WordPressGenerationError):
    """Fact Grounding 검증(fact_validation.validate_fact_grounding)이
    FAIL 판정을 내렸을 때 발생한다. result에 상세 사유가 담겨 있다.
    """

    def __init__(self, result: FactValidationResult) -> None:
        self.result = result
        parts = ["Fact Grounding 검증 실패(FAIL)."]
        if result.invalid_fact_ids:
            parts.append(f"존재하지 않는 Fact ID: {result.invalid_fact_ids}")
        if result.unsupported_numbers:
            parts.append(f"근거 없는 수치/날짜: {result.unsupported_numbers}")
        super().__init__(" ".join(parts))


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_DECIMAL_NUMBER_RE = re.compile(r"\d+\.\d+")

_SYSTEM_PROMPT = """당신은 금융/거시경제 리서치 라이터다.

[가장 중요한 규칙 - Anti-Hallucination]
제공된 MasterContent만 사실의 근거로 사용한다.
MasterContent에 없는 숫자, 날짜, 인물 발언, 정책 내용, 시장 가격을
만들어내지 않는다.
정보가 부족하면 해당 내용을 생략하거나 "확인 필요"로 표시한다.

[문체 규칙]
- 한국어 존댓말이 아닌 객관적인 리서치 문체를 사용한다.
- 과도한 클릭베이트, 불필요한 감탄사를 쓰지 않는다.
- SEO 키워드를 반복하지 않는다.
- 전문용어는 첫 등장 시 짧게 설명한다.
- 숫자는 가능하면 기준일과 단위를 함께 표기한다.
- source_type이 primary인 자료를 우선적으로 언급한다.
- confidence가 low로 표시된 사실은 확정적으로 표현하지 않는다
  ("~일 수 있다", "~로 보인다" 등으로 표현한다).
- bull_case와 bear_case를 균형 있게 다룬다.
- MasterContent에 없는 전망이나 예측을 임의로 만들어내지 않는다.

[본문 구조]
content_markdown은 마크다운으로 작성한다. 아래 순서를 기본 구조로
삼되, 해당 주제에 필요 없는 섹션은 억지로 채우지 말고 생략한다. 각
섹션은 "## 소제목"으로 구분한다.
1. 핵심 답변 (40~80자, 첫 문단)
2. 핵심 숫자/사실 (최대 3개, 목록)
3. 무슨 일이 일어났나
4. 왜 중요한가
5. 인과관계
6. 채권시장 영향
7. 주식시장 영향
8. Bull case
9. Bear case
10. 주요 리스크
11. thesis를 무효화할 수 있는 조건
12. 앞으로 확인해야 할 지표
13. 핵심 요약
글 제목(H1)과 출처 목록은 만들지 않는다 (시스템이 별도로 처리한다).

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다
(예: "fact_001"). 본문에서 구체적인 수치/날짜/주장의 근거로 사용한
fact의 id를 모두 used_fact_ids 배열에 넣는다. 사용하지 않은 fact의
id는 넣지 않는다. facts 목록에 없는 id를 지어내지 않는다.

[출력 형식]
다른 설명, 코드펜스, 부가 텍스트 없이 아래 키를 가진 JSON 객체 하나만
출력한다. content_html, source_list, generated_at 키는 포함하지 않는다
(시스템이 직접 계산한다).

{
  "title": string,
  "slug": string,
  "excerpt": string,
  "meta_description": string,
  "content_markdown": string,
  "primary_keyword": string,
  "related_keywords": string[],
  "used_fact_ids": string[]
}
"""


def _build_user_prompt(content: MasterContent) -> str:
    payload = {
        "topic": content.meta.topic,
        "market_data": content.market_data.model_dump(mode="json"),
        "analysis": content.analysis.model_dump(mode="json"),
    }
    master_content_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "다음은 이번 글 작성에 사용할 MasterContent(JSON)이다. "
        "이 안에 있는 정보만 사실의 근거로 사용하라.\n\n"
        f"```json\n{master_content_json}\n```\n\n"
        "위 MasterContent만 근거로 삼아 WordPress 분석글을 시스템 프롬프트의 "
        "JSON 스키마에 맞춰 작성하라."
    )


def _extract_json_text(raw: str) -> str:
    match = _JSON_BLOCK_RE.search(raw)
    return match.group(1) if match else raw.strip()


def _parse_llm_response(raw: str) -> dict:
    json_text = _extract_json_text(raw)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise WordPressGenerationError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {exc}") from exc
    if not isinstance(data, dict):
        raise WordPressGenerationError("LLM 응답 JSON이 객체(object) 형태가 아닙니다.")
    return data


def _build_article(data: dict) -> WordPressArticle:
    try:
        return WordPressArticle.model_validate(data)
    except ValidationError as exc:
        raise WordPressGenerationError(
            f"LLM 응답이 WordPressArticle 스키마와 맞지 않습니다: {exc}"
        ) from exc


def _normalize_number(value: object) -> str | None:
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return None


def _collect_allowed_numbers(content: MasterContent) -> set[str]:
    """본문에 등장해도 되는(=MasterContent에 실제로 존재하는) 소수점 숫자 집합."""
    numbers: set[str] = set()

    def add(value: object) -> None:
        normalized = _normalize_number(value)
        if normalized is not None:
            numbers.add(normalized)

    for point in (
        *content.market_data.indices,
        *content.market_data.fx,
        *content.market_data.commodities,
    ):
        add(point.value)
        add(point.change_percent)

    for event in content.market_data.macro_events:
        for text in (event.actual, event.forecast, event.previous):
            if text:
                for match in _DECIMAL_NUMBER_RE.findall(text):
                    add(match)

    for fact in content.analysis.facts:
        add(fact.value)

    return numbers


def _check_for_hallucinated_numbers(article: WordPressArticle, content: MasterContent) -> None:
    """content_markdown 안의 소수점 숫자가 MasterContent에 실제로 존재하는지
    확인하는 최소 수준의 환각 방지 검증이다.

    정수/퍼센트 등 소수점이 없는 숫자는 본문 어디에나 흔히 등장해
    오탐(false positive)이 너무 많으므로 이번 단계에서는 검사 대상에서
    제외한다. 완전한 사실 검증이 아니라 "명백히 근거 없는 정밀 수치"를
    걸러내기 위한 최소 장치다.
    """
    allowed = _collect_allowed_numbers(content)
    found = {
        normalized
        for raw_number in _DECIMAL_NUMBER_RE.findall(article.content_markdown)
        if (normalized := _normalize_number(raw_number)) is not None
    }
    unknown = found - allowed
    if unknown:
        raise HallucinationDetectedError(
            "MasterContent에 없는 수치가 생성된 본문에 포함되어 있습니다: "
            + ", ".join(sorted(unknown))
        )


def _build_source_list(content: MasterContent, used_fact_ids: list[str] | None = None) -> list[str]:
    """LLM이 아니라 MasterContent.analysis에서 직접 만든 출처 목록.

    LLM이 출처를 지어내는 것을 막기 위해, source_list는 항상 이
    함수의 결과로 덮어쓴다. used_fact_ids(검증을 통과한 것만)가 있으면
    실제로 본문 작성에 쓰인 fact의 source를 최우선으로 사용하고,
    없으면 기존처럼 analysis.sources 전체, 그마저도 없으면 모든
    fact의 source로 대체한다.
    """
    entries: list[str] = []
    seen: set[str] = set()

    def add(label: str | None) -> None:
        if label and label not in seen:
            seen.add(label)
            entries.append(label)

    if used_fact_ids:
        fact_by_id = {fact.id: fact for fact in content.analysis.facts if fact.id}
        for fact_id in used_fact_ids:
            fact = fact_by_id.get(fact_id)
            if fact:
                add(fact.source)

    if not entries:
        for source in content.analysis.sources:
            add(f"{source.name} ({source.url})" if source.url else source.name)

    if not entries:
        for fact in content.analysis.facts:
            add(fact.source)

    return entries


def _render_sources_html(source_list: list[str]) -> str:
    if not source_list:
        return ""
    items = "".join(f"<li>{html.escape(s)}</li>" for s in source_list)
    return f"<h2>출처</h2>\n<ul>{items}</ul>"


def generate_wordpress_content(
    content: MasterContent, *, llm_client: LlmClient | None = None
) -> MasterContent:
    """MasterContent.market_data/analysis 를 근거로 wordpress 필드를 채운다.

    llm_client 를 넘기지 않으면 실제 Anthropic API를 호출하는
    LlmClient()를 새로 만든다 (테스트에서는 가짜 client를 주입한다).
    LLM 호출 자체가 실패하면(LlmClientError 계열) 그대로 전파한다.
    """
    client = llm_client or LlmClient()

    raw_response = client.generate(
        _build_user_prompt(content),
        system_prompt=_SYSTEM_PROMPT,
        max_tokens=DEFAULT_ARTICLE_MAX_TOKENS,
    )

    data = _parse_llm_response(raw_response)
    article = _build_article(data)

    # 1차 방어선(기존, 유지): 본문의 소수점 숫자가 MasterContent에 있는지
    # 최소한으로 대조한다. 여기서 걸리면 아래 content.wordpress 반영까지
    # 진행하지 않는다.
    _check_for_hallucinated_numbers(article, content)

    # 2차 방어선(신규): Fact ID + 퍼센트/bp/금액/날짜를 구조적으로 대조한다.
    # FAIL이면 역시 content.wordpress 를 반영하지 않고 예외로 막는다.
    # REVIEW_REQUIRED는 막지 않고 결과를 wordpress 필드에 남겨 향후
    # (자동 발행하지 않는) draft 판단에 쓸 수 있게 한다.
    fact_result = validate_fact_grounding(article, content)
    if fact_result.status == FactValidationStatus.FAIL:
        raise FactGroundingError(fact_result)

    # source_list는 LLM 응답을 무시하고, 검증된 used_fact_ids가 있으면
    # 실제로 쓰인 fact의 source를 우선해 MasterContent 기반으로 다시 만든다.
    article.source_list = _build_source_list(content, used_fact_ids=fact_result.used_fact_ids)

    body_html = markdown_to_html(article.content_markdown)
    sources_html = _render_sources_html(article.source_list)
    article.content_html = body_html + ("\n" + sources_html if sources_html else "")

    content.wordpress = WordPressContent(
        title=article.title,
        slug=article.slug,
        excerpt=article.excerpt,
        content_html=article.content_html,
        content_markdown=article.content_markdown,
        tags=article.related_keywords,
        categories=[],
        source_list=article.source_list,
        fact_validation_status=fact_result.status.value,
        fact_validation_warnings=fact_result.warnings,
        used_fact_ids=fact_result.used_fact_ids,
        seo=SeoMeta(
            meta_title=article.title,
            meta_description=article.meta_description,
            focus_keyword=article.primary_keyword,
        ),
    )
    content.touch()
    return content
