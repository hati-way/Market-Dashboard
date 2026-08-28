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
from modules.master_content.schema import (
    Fact,
    InternalLink,
    MasterContent,
    SeoMeta,
    Source,
    SourceType,
    WordPressContent,
)

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

_SYSTEM_PROMPT = """당신은 "돈맥" 매체의 거시경제 리서치 라이터다.
목표는 "안전하지만 특징 없는 AI 리포트"가 아니라, 실제 발행 가능한
거시경제 해석 글이다. 핵심은 단순 뉴스 요약이 아니라 "무엇이 변했고,
그 변화가 자본 흐름에 어떻게 전달되는가"를 압축적으로 설명하는 것이다.

[가장 중요한 규칙 - Anti-Hallucination]
제공된 MasterContent만 사실의 근거로 사용한다.
MasterContent에 없는 숫자, 날짜, 인물 발언, 정책 내용, 시장 가격을
만들어내지 않는다.
정보가 부족하면 해당 내용을 생략하거나 "확인 필요"로 표시한다.

[문체 규칙]
- 한국어 존댓말이 아닌 객관적인 리서치 문체를 사용한다.
- 문장은 짧고 직접적으로 쓴다. 과도한 클릭베이트, 불필요한 감탄사를
  쓰지 않는다.
- SEO 키워드를 반복하지 않는다.
- 전문용어는 첫 등장 시에만 짧게 병기 설명하고(예: "유동성 프리미엄
  (liquidity premium)"), 이후에는 한국어 용어만 쓴다.
- 숫자는 가능하면 기준일과 단위를 함께 표기한다.
- source_type이 primary인 자료를 우선적으로 언급한다.
- 같은 숫자, 같은 인과관계를 여러 섹션에서 반복하지 않는다. 한 번
  명확하게 말하고, 다른 섹션에서는 그 위에 새로운 해석을 더한다.
- 다음과 같은 AI 리포트 특유의 상투어를 쓰지 않는다: "제공된 분석에
  따르면", "자료에 따르면", "본 분석에서는", "~로 해석될 수 있다"의
  반복, "~할 필요가 있다"의 반복, "상반된 해석을 동시에 안고 있다",
  "시장 심리에 긍정적으로 작용할 가능성". 예를 들어 "재무부의 바이백
  규모 확대는 국채 발행 및 유동성 관리 정책의 방향성을 보여주는
  신호로 해석될 수 있다" 대신 "중요한 건 바이백 규모 자체보다
  재무부가 국채 시장의 어느 구간을 지원하려 하는지다"처럼 쓴다.

[사실과 해석의 구분]
본문 전체에서 다음 네 가지를 명확히 구분해서 쓴다.
1. 확인된 사실 (MasterContent의 facts/market_data)
2. 관찰된 시장 반응 (지수/환율 등의 실제 변화)
3. 해석 (그 사실이 왜 중요한지에 대한 설명)
4. 시나리오 (앞으로 있을 수 있는 전개, 조건부로만 서술)
confidence가 low이거나 source_type이 secondary(예: "시장 컨센서스",
"딜러 서베이")인 내용은 확정적 문장으로 쓰지 않는다. "~로 본다",
"~일 수 있다", "일부 시장 참여자는 ~라고 본다"처럼 주체와 불확실성을
함께 표현한다.
나쁜 예: "바이백 확대는 장기물 발행 부담을 낮춘다."
좋은 예: "일부 시장 참여자는 바이백 확대가 유동성 프리미엄을 낮춰
장기물 발행 부담을 완화할 가능성이 있다고 본다."

[인과관계 표현]
정책/사건이 자산가격에 닿기까지의 경로를 설명할 때는 다음 흐름을
참고하되, 화살표로 이어붙인 단정적 인과로 쓰지 않는다.
  정책/사건 → 수급 또는 유동성 변화 → 금리/변동성/리스크 프리미엄
  변화 가능성 → 자산시장 영향
나쁜 예("자동적 인과"로 단정): "바이백 확대 → 장기금리 하락 → 주식
상승."
좋은 예(조건부 서술): "바이백 확대가 특정 만기의 유동성과 수급을
개선하면 유동성 프리미엄과 금리 변동성이 완화될 수 있고, 그 경우
위험자산에는 우호적인 환경이 형성될 수 있다."
MasterContent의 causal_chain/market_implications는 이 조건부 설명을
만들 때의 재료로만 쓰고, 그대로 나열하지 않는다.

[본문 구조]
content_markdown은 마크다운으로 작성한다. 아래 8개 섹션을 기본
구조로 삼되, 해당 주제에 필요 없는 섹션은 억지로 채우지 말고
생략한다. 채권시장 영향/주식시장 영향처럼 겹치는 내용은 "시장에
전달되는 경로" 한 섹션으로 통합해서 쓴다. 각 섹션은 "## 소제목"으로
구분하고, 아래 한글 소제목을 그대로 쓴다(영어 소제목 금지 — "Bull
case"/"Bear case"/"thesis"/"invalidation" 같은 표현을 쓰지 않는다).
1. ## 핵심 답변 (40~80자, 첫 문단. 결론부터 말한다)
2. ## 무슨 일이 있었나 (확인된 사실 + 관찰된 시장 반응, 핵심 숫자는
   여기서 한 번만 명시한다)
3. ## 왜 중요한가
4. ## 시장에 전달되는 경로 (위 "인과관계 표현" 규칙에 따라 조건부로
   서술. 채권/주식/환율 등 여러 자산에 걸치면 이 섹션 안에서 함께
   다룬다)
5. ## 긍정적으로 볼 수 있는 이유 / ## 반대로 봐야 할 위험 (원래의
   bull/bear case를 한국어로 쓴다. 둘 다 MasterContent 근거가 있을
   때만 쓰고, 없으면 생략한다)
6. ## 이 해석이 틀릴 수 있는 조건 (원래의 invalidating_conditions를
   한국어로 쓴다)
7. ## 앞으로 확인할 지표 (원래의 update_triggers)
8. ## 핵심 요약 (마지막 문단에서, 투자 추천 문체는 피하면서, 가능하면
   자본이 어디를 보고 있는지 / 시장이 아직 가격에 반영하지 않은 것이
   무엇인지 / 다음에 확인할 지표가 무엇인지를 연결해서 마무리한다)
글 제목(H1)과 출처 목록, 내부링크는 만들지 않는다(시스템이 별도로
처리한다). content_markdown 안에서 "#"(h1)을 쓰지 않고 "##"부터
시작한다.

[길이]
전체 분량은 한글 기준 약 1,500~2,500자를 목표로 한다. MasterContent에
정보가 부족한 주제를 억지로 늘리지 않고, 정보가 많아도 같은 내용을
반복해서 채우지 않는다.

[제목(title)]
title은 화면에 보이는 H1이다. 다음을 지킨다.
- 핵심 키워드를 포함한다.
- 모바일 화면에서 2~3줄 이상으로 줄바꿈되지 않도록 간결하게 쓴다
  (한글 기준 대략 45자 이내를 목표로 한다).
- 질문형 또는 의미를 압축한 형태 모두 가능하다.
- 클릭베이트(과장된 감탄, 낚시성 표현)를 쓰지 않는다.
- 예: "미국 국채 바이백 300억 달러 확대, 시장에 어떤 의미일까"
seo_title은 검색결과에 노출될 title이다. title과 똑같아도 되지만,
필요하면 핵심 키워드를 조금 더 담아 title과 다르게 쓸 수 있다(예:
title은 간결하게, seo_title에는 "미국 국채 바이백"과 "장기금리" 같은
검색 키워드를 함께 포함).

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
  "seo_title": string,
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
    """본문에 등장해도 되는(=MasterContent에 실제로 존재하는) 소수점 숫자 집합.

    _DECIMAL_NUMBER_RE(`\\d+\\.\\d+`)는 부호(-)를 애초에 캡처하지 않으므로
    본문에서 추출되는 값은 항상 부호 없는 절대값이다("하락했다"처럼 방향을
    단어로 표현하거나, 설령 "-0.03%"처럼 명시적으로 부호를 써도 정규식은
    "0.03"만 잡는다). 반면 change_percent 같은 값은 MasterContent에 부호가
    있는 채로("-0.03") 저장되어 있어, 부호를 그대로 허용 목록에 넣으면
    음수인 실제 수치를 본문에 아무리 정확히 옮겨 적어도 절대 매칭되지
    않는다. 그래서 음수 값은 절대값도 함께 허용 목록에 넣어 이 비대칭을
    바로잡는다(값 자체를 새로 허용하는 게 아니라, 어차피 부호를 검사할 수
    없는 이 정규식 기준에 맞춰 비교 방식을 맞추는 것이다).
    """
    numbers: set[str] = set()

    def add(value: object) -> None:
        normalized = _normalize_number(value)
        if normalized is not None:
            numbers.add(normalized)
            if normalized.startswith("-"):
                numbers.add(normalized[1:])

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


def _source_lookup(content: MasterContent) -> dict[str, Source]:
    return {source.name: source for source in content.analysis.sources}


def _format_source_entry(
    name: str, url: str | None, as_of: str | None, source_type: SourceType
) -> str:
    """출처 하나를 "기관명 — 기준일 — URL" 형태로 만든다.

    URL이 MasterContent에 없으면(fact/Source 어디에도 없으면) 임의로
    만들지 않고 "URL 미제공"으로만 표시한다. 2차 출처(secondary)이면서
    URL도 없는 경우(예: "시장 컨센서스", "딜러 서베이")는 원자료를
    확인할 수 없다는 한계를 문구로 명시한다.
    """
    parts = [name]
    if as_of:
        parts.append(as_of)
    parts.append(url if url else "URL 미제공")
    entry = " — ".join(parts)
    if not url and source_type in (SourceType.SECONDARY, SourceType.UNKNOWN):
        entry += " (2차 출처, 원자료 URL 미확인)"
    return entry


def _entry_for_fact(fact: Fact, lookup: dict[str, Source]) -> str:
    """fact.source 이름으로 analysis.sources에서 URL/source_type을 찾아
    쓰고(있으면), 없으면 fact 자체의 source_type만으로 표시한다. 둘 다
    MasterContent 안의 값만 쓴다 - URL을 새로 만들지 않는다.
    """
    matched = lookup.get(fact.source)
    url = matched.url if matched else None
    source_type = matched.source_type if matched else fact.source_type
    as_of = fact.date.isoformat() if fact.date else None
    return _format_source_entry(fact.source, url, as_of, source_type)


def _entry_for_source(source: Source) -> str:
    return _format_source_entry(source.name, source.url, as_of=None, source_type=source.source_type)


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
    lookup = _source_lookup(content)

    def add(entry: str | None) -> None:
        if entry and entry not in seen:
            seen.add(entry)
            entries.append(entry)

    if used_fact_ids:
        fact_by_id = {fact.id: fact for fact in content.analysis.facts if fact.id}
        for fact_id in used_fact_ids:
            fact = fact_by_id.get(fact_id)
            if fact:
                add(_entry_for_fact(fact, lookup))

    if not entries:
        for source in content.analysis.sources:
            add(_entry_for_source(source))

    if not entries:
        for fact in content.analysis.facts:
            add(_entry_for_fact(fact, lookup))

    return entries


_URL_IN_TEXT_RE = re.compile(r"https?://\S+")


def _linkify_source_entry(entry: str) -> str:
    """출처 문자열 안에 이미 있는 URL(있다면)만 <a> 태그로 바꾼다.

    URL을 새로 만들지 않는다 - _build_source_list()가 만든 문자열
    (예: "기관명 — 기준일 — https://...")에 실제로 포함된 URL만 찾아
    그 부분만 링크로 바꾸고, 나머지 텍스트는 그대로 이스케이프한다.
    URL이 없으면(예: "URL 미제공") 전체를 이스케이프만 한다.
    """
    match = _URL_IN_TEXT_RE.search(entry)
    if not match:
        return html.escape(entry)
    url = match.group(0)
    before = html.escape(entry[: match.start()])
    after = html.escape(entry[match.end() :])
    link = f'<a href="{html.escape(url)}" rel="nofollow noopener" target="_blank">{html.escape(url)}</a>'
    return before + link + after


def _render_sources_html(source_list: list[str]) -> str:
    if not source_list:
        return ""
    items = "".join(f"<li>{_linkify_source_entry(s)}</li>" for s in source_list)
    return f"<h2>출처</h2>\n<ul>{items}</ul>"


def _render_internal_links_html(internal_links: list[InternalLink]) -> str:
    """MasterContent.analysis.internal_links가 있을 때만 내부링크 섹션을
    만든다. 아직 내부링크 자동 추천 시스템이 없으므로, 이 목록이
    비어 있으면(기본값) 아무것도 만들지 않는다 - 가짜 링크를 넣지
    않기 위함이다.
    """
    if not internal_links:
        return ""
    items = "".join(
        f'<li><a href="{html.escape(link.url)}">{html.escape(link.title)}</a></li>'
        for link in internal_links
    )
    return f"<h2>관련 글</h2>\n<ul>{items}</ul>"


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
    internal_links_html = _render_internal_links_html(content.analysis.internal_links)
    article.content_html = (
        body_html
        + ("\n" + sources_html if sources_html else "")
        + ("\n" + internal_links_html if internal_links_html else "")
    )

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
            # seo_title이 비어 있으면(기존 동작과 호환) title을 그대로 쓴다.
            meta_title=article.seo_title or article.title,
            meta_description=article.meta_description,
            focus_keyword=article.primary_keyword,
        ),
    )
    content.touch()
    return content
