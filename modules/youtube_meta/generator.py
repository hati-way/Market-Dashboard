"""8단계: 같은 MasterContent로 YouTube 제목/설명/태그/고정댓글 생성.

generate_youtube_meta() (기존, placeholder)는 pipeline/orchestrator.py의
단일 WordPress 파이프라인이 계속 쓰므로 그대로 남겨 두었다.

generate_youtube_output() (신규)이 실제 Anthropic Claude 기반 생성이다.
pipeline/multi_channel.py의 새 다채널 생성 파이프라인이 이 함수를 쓴다.
WordPressArticle을 거치지 않고 MasterContent.market_data/analysis를
직접 입력받는다.

실제 --generate-all 실행에서 YouTube 채널만 "LLM 응답을 JSON으로
파싱하지 못했습니다: Expecting value: line 1 column 1"로 실패한 적이
있다. 원인은 modules.shared_grounding.generation_support.parse_llm_json
이 코드펜스(```json ... ```)가 있는 응답만 안정적으로 처리하고,
펜스 없이 앞에 설명 문구가 붙은 응답("Here's the metadata:\n\n{...}")
은 raw.strip() 그대로 json.loads에 넘겨 실패했기 때문이다(Threads/
NotebookLM/Thumbnail도 이론적으로 같은 문제가 있을 수 있지만, 이번
라운드에서는 실제로 실패가 보고된 YouTube만 고친다 - 다른 채널
로직은 건드리지 않는다). 그래서 이 모듈만 별도로 더 안정적인 JSON
추출(_extract_json_object, 코드펜스 유무와 무관하게 첫 "{"부터 중괄호
깊이를 세어 대응하는 "}"까지 추출)과, 실패 시 최대 1회의 schema-repair
재시도를 쓴다. 이 로직은 다른 채널과 공유하지 않는다(shared_grounding
의 parse_llm_json/GenerationParsingError는 그대로 두었고 이 파일만
독립적으로 더 안정적인 버전을 쓴다).
"""
from __future__ import annotations

import json
import logging
import math
import re

from pydantic import ValidationError

from clients.llm_client import LlmClient
from modules.master_content.schema import MasterContent, YoutubeChapter, YoutubeMeta
from modules.shared_grounding.fact_validation import FactValidationStatus, validate_text_grounding
from modules.shared_grounding.generation_support import (
    HallucinationDetectedError,
    check_for_hallucinated_numbers,
)

from .models import YouTubeOutput

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 2048
MAX_ATTEMPTS = 2  # 원래 시도 1회 + schema-repair 재시도 최대 1회.
_PREVIEW_LENGTH = 80

MIN_CHAPTERS = 4
MAX_CHAPTERS = 7
# NotebookLM 대본의 목표 분량(4~7분) 중간값. 실제 영상 편집 전이라 정확한
# 러닝타임을 알 수 없으므로, 챕터 후보에 붙이는 타임스탬프는 이 값을
# 균등하게 나눈 "예상" 값이다(실제 편집 후 다시 맞춰야 하는 출발점).
_ASSUMED_VIDEO_SECONDS = 300

# title_candidates/recommended_title/description/pinned_comment처럼
# 시청자에게 그대로 노출되는 필드에 내부 Fact ID("fact_004" 등)가 섞여
# 나오면 안 된다 - used_fact_ids 배열에만 담겨야 하는 내부 식별자다.
_INTERNAL_ID_RE = re.compile(r"\bfact_[a-z0-9]+\b", re.IGNORECASE)


class YoutubeGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


class YoutubeInternalIdLeakError(YoutubeGenerationError):
    """시청자에게 노출되는 필드에 내부 fact id가 그대로 섞여 나왔을 때 발생한다.

    fact_004 같은 식별자는 used_fact_ids 배열에만 담겨야 하는 내부
    bookkeeping 값이다. 시청자가 보는 title/description/pinned_comment에
    이 값이 그대로 노출되면 안 되므로 구조 검증과 같은 수준으로 막는다
    (schema-repair 재시도 대상이기도 하다).
    """


class YoutubeFactGroundingError(YoutubeGenerationError):
    """Fact Grounding 검증이 FAIL 판정을 내렸을 때 발생한다."""

    def __init__(self, result) -> None:  # noqa: ANN001
        self.result = result
        parts = ["YouTube Fact Grounding 검증 실패(FAIL)."]
        if result.invalid_fact_ids:
            parts.append(f"존재하지 않는 Fact ID: {result.invalid_fact_ids}")
        if result.unsupported_numbers:
            parts.append(f"근거 없는 수치/날짜: {result.unsupported_numbers}")
        super().__init__(" ".join(parts))


def generate_youtube_meta(content: MasterContent) -> MasterContent:
    """기존 placeholder 구현(변경하지 않음). wordpress/notebooklm 콘텐츠를 재활용한다."""
    wp = content.wordpress

    content.youtube = YoutubeMeta(
        title=wp.title,
        description=wp.excerpt,
        chapters=[YoutubeChapter(timestamp="00:00", title="인트로")],
        pinned_comment=f"오늘의 주제: {wp.title}\n{wp.excerpt}",
        tags=wp.tags,
    )
    content.touch()
    return content


_SYSTEM_PROMPT = """당신은 "돈맥" 매체의 YouTube 메타데이터 작가다.

[가장 중요한 규칙 - Anti-Hallucination]
제공된 MasterContent만 사실의 근거로 사용한다.
MasterContent에 없는 숫자, 날짜, 인물 발언, 정책 내용, 시장 가격을
만들어내지 않는다. 실제 내용보다 강한 단정을 하지 않는다.
confidence가 low이거나 source_type이 secondary(예: "시장 컨센서스")인
내용은 확정적으로 쓰지 않는다. "일부 시장 참여자는 ~라고 본다"처럼
주체와 불확실성을 함께 자연어로 표현한다 - 이때도 fact_004 같은 내부
식별자를 절대 언급하지 않는다(아래 [내부 식별자 노출 금지] 참고).

[내부 식별자 노출 금지]
MasterContent.analysis.facts의 각 항목에는 "fact_001"처럼 내부용 id가
있다. 이 id는 오직 used_fact_ids 배열에만 넣는다. title_candidates,
recommended_title, description, pinned_comment, tags 등 시청자가 실제로
보게 되는 어떤 필드에도 "fact_001", "fact_004" 같은 식별자 문자열을
절대 쓰지 않는다. 근거를 밝히고 싶으면 "재무부 발표에 따르면"처럼
자연어 문구로만 쓴다.

[제목(title_candidates/recommended_title) 규칙]
- 후보 5개를 만들고, 그중 하나를 recommended_title로 고른다.
- 45~70자 권장.
- 사람의 궁금증을 유도하되 지나친 공포/탐욕 클릭베이트는 금지한다.
- 핵심 경제 키워드를 포함한다.
- 예: "미국이 국채를 다시 사들이는 이유, 300억 달러 바이백의 진짜 의미"

[설명(description) 문체 - 자연스러운 영상 설명문]
description은 기사/리포트처럼 딱딱하게 쓰지 않는다. 시청자에게 말을
거는 자연스러운 영상 설명문으로 쓴다.
- 첫 2줄에 이 영상의 핵심 내용을 압축해서 담는다(시청자가 스크롤하지
  않고도 무슨 영상인지 바로 알 수 있어야 한다).
- 그다음 이 영상이 다루는 주요 포인트를 짧게 풀어 쓴다(번호를 매긴
  나열보다는 자연스러운 문장 흐름을 우선하되, 필요하면 짧은 목록도
  괜찮다).
- 출처를 명시한다(MasterContent의 sources/facts에 있는 기관명만 쓴다).
- 투자 권유가 아니라는 점을 한 줄로 짧게 명시할 수 있다.
- "본 영상은 다음을 분석합니다" 같은 보고서체 상투어를 쓰지 않는다.

[tags]
- 정확히 5~8개를 만든다.
- 의미가 겹치는 태그를 만들지 않는다("국채"와 "미국국채"처럼 사실상
  같은 표현을 중복해서 넣지 않는다). 서로 다른 각도의 키워드로
  구성한다(예: 사건, 기관, 자산군, 지표).

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다.
설명/고정댓글에서 구체적인 수치/날짜/주장의 근거로 사용한 fact의 id를
모두 used_fact_ids 배열에 넣는다. facts 목록에 없는 id를 지어내지
않는다. (다시 강조: 이 id를 title/description/pinned_comment 본문에는
절대 쓰지 않는다.)

[출력 형식 - 반드시 지킬 것]
응답은 오직 유효한 JSON object 하나여야 한다.
- 코드펜스(```)로 감싸지 않는다.
- JSON 앞뒤에 어떤 설명, 인사말, 요약, 주석도 붙이지 않는다("다음은
  요청하신 메타데이터입니다" 같은 문장을 포함하지 않는다).
- 응답의 첫 글자는 반드시 "{"이고 마지막 글자는 반드시 "}"여야 한다.
- 이 규칙을 지키지 않으면 시스템이 응답을 파싱하지 못해 이 콘텐츠가
  전혀 반영되지 못한다.

아래 키를 정확히 포함한 JSON object 하나만 출력한다.

{
  "title_candidates": string[],
  "recommended_title": string,
  "description": string,
  "tags": string[],
  "pinned_comment": string,
  "used_fact_ids": string[]
}
"""

# schema-repair 재시도 전용 프롬프트. 원래 지침을 반복하지 않고, 오직
# "설명 없이 JSON object만" + "내부 식별자 금지" + "tags 개수"를 강하게
# 재확인만 시킨다.
_REPAIR_SYSTEM_PROMPT = """직전 응답이 유효하지 않았다(JSON으로 파싱되지
않았거나, 스키마와 맞지 않았거나, title/description/pinned_comment에
fact_001 같은 내부 식별자가 그대로 섞여 있었다).

지금부터 다시 시도한다. 이전 응답을 설명하거나 사과하지 않는다. 왜
실패했는지 언급하지 않는다. 다른 텍스트, 코드펜스, 마크다운, 주석 없이
오직 유효한 JSON object 하나만 출력한다. 응답의 첫 글자는 "{"이고
마지막 글자는 "}"여야 한다.

fact_001, fact_004 같은 내부 식별자는 used_fact_ids 배열에만 넣고,
title_candidates/recommended_title/description/pinned_comment에는 절대
쓰지 않는다. tags는 정확히 5~8개, 의미가 겹치지 않게 만든다.

아래 키를 정확히 포함한 JSON object 하나만 출력한다.

{
  "title_candidates": string[],
  "recommended_title": string,
  "description": string,
  "tags": string[],
  "pinned_comment": string,
  "used_fact_ids": string[]
}
"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _response_preview(raw: str) -> str:
    """로그/에러 메시지에 남길 안전한 미리보기. 실제 raw 전체를 남기지
    않고 길이와 앞부분 일부만 남긴다.
    """
    if not raw:
        return "(빈 응답)"
    stripped = raw.strip()
    if not stripped:
        return "(공백만 있는 응답)"
    preview = stripped[:_PREVIEW_LENGTH].replace("\n", " ")
    suffix = "..." if len(stripped) > _PREVIEW_LENGTH else ""
    return f"{preview}{suffix}"


def _strip_code_fences(raw: str) -> str:
    """```json ... ``` 또는 ``` ... ``` 코드펜스가 있으면 그 안의
    내용만 꺼낸다. 여러 펜스가 있으면 첫 번째만 쓴다. 펜스가 없으면
    원본을 그대로(양끝 공백만 제거해서) 돌려준다.
    """
    match = _JSON_FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def _extract_json_object(raw: str) -> str:
    """응답 앞뒤에 설명 문구가 붙어 있어도(코드펜스가 있든 없든) 첫
    "{"부터 그에 대응하는 "}"까지를 중괄호 깊이를 세어 안전하게
    추출한다. 문자열 리터럴 안의 중괄호/이스케이프된 따옴표는 깊이
    계산에서 제외한다.
    """
    if not raw or not raw.strip():
        raise YoutubeGenerationError("LLM 응답이 비어 있습니다.")

    text = _strip_code_fences(raw)
    start = text.find("{")
    if start == -1:
        raise YoutubeGenerationError(
            "LLM 응답에서 JSON 객체를 찾지 못했습니다 "
            f"(길이={len(raw)}자, 미리보기: \"{_response_preview(raw)}\")."
        )

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise YoutubeGenerationError(
        "LLM 응답에서 닫는 중괄호를 찾지 못해 JSON 객체를 추출하지 못했습니다 "
        f"(길이={len(raw)}자, 미리보기: \"{_response_preview(raw)}\")."
    )


def _parse_youtube_json(raw: str) -> dict:
    json_text = _extract_json_object(raw)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise YoutubeGenerationError(
            "LLM 응답을 JSON으로 파싱하지 못했습니다 "
            f"(길이={len(raw)}자, 미리보기: \"{_response_preview(raw)}\"): {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise YoutubeGenerationError(
            "LLM 응답 JSON이 객체(object) 형태가 아닙니다 "
            f"(길이={len(raw)}자, 미리보기: \"{_response_preview(raw)}\")."
        )
    return data


def _build_user_prompt(content: MasterContent) -> str:
    payload = {
        "topic": content.meta.topic,
        "market_data": content.market_data.model_dump(mode="json"),
        "analysis": content.analysis.model_dump(mode="json"),
    }
    master_content_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "다음은 이번 YouTube 메타데이터 작성에 사용할 MasterContent(JSON)이다. "
        "이 안에 있는 정보만 사실의 근거로 사용하라.\n\n"
        f"```json\n{master_content_json}\n```\n\n"
        "위 MasterContent만 근거로 삼아 YouTube 메타데이터를 시스템 프롬프트의 "
        "JSON 스키마에 맞춰 작성하라."
    )


def _build_output(data: dict) -> YouTubeOutput:
    try:
        return YouTubeOutput.model_validate(data)
    except ValidationError as exc:
        raise YoutubeGenerationError(
            f"LLM 응답이 YouTubeOutput 스키마와 맞지 않습니다: {exc}"
        ) from exc


def _check_no_internal_ids_leaked(output: YouTubeOutput) -> None:
    """title_candidates/recommended_title/description/pinned_comment 등
    시청자에게 노출되는 필드에 내부 fact id(예: "fact_004")가 그대로
    섞여 있으면 막는다. used_fact_ids 필드 자체는 검사 대상이 아니다
    (거기엔 정당하게 id가 들어간다).
    """
    user_facing_fields: dict[str, str] = {
        "recommended_title": output.recommended_title,
        "description": output.description,
        "pinned_comment": output.pinned_comment,
    }
    for i, candidate in enumerate(output.title_candidates):
        user_facing_fields[f"title_candidates[{i}]"] = candidate
    for i, tag in enumerate(output.tags):
        user_facing_fields[f"tags[{i}]"] = tag

    leaked = {
        field: sorted(set(_INTERNAL_ID_RE.findall(text)))
        for field, text in user_facing_fields.items()
        if _INTERNAL_ID_RE.search(text)
    }
    if leaked:
        details = "; ".join(f"{field}={ids}" for field, ids in leaked.items())
        raise YoutubeInternalIdLeakError(
            f"시청자에게 노출되는 필드에 내부 fact id가 섞여 있습니다: {details}"
        )


def _parse_and_build(raw_response: str) -> YouTubeOutput:
    data = _parse_youtube_json(raw_response)
    output = _build_output(data)
    _check_no_internal_ids_leaked(output)
    return output


def _format_timestamp(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, total_seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _condense_to_chapter_titles(titles: list[str]) -> list[str]:
    """제목 목록을 4~7개로 맞춘다. MAX_CHAPTERS보다 많으면 그룹으로 묶어
    각 그룹의 대표 제목만 남긴다(비어 있는 자리를 지어내 채우지 않는다
    - MIN_CHAPTERS보다 적으면 있는 그대로 둔다).
    """
    if not titles:
        return []
    if len(titles) <= MAX_CHAPTERS:
        return titles
    group_size = math.ceil(len(titles) / MAX_CHAPTERS)
    condensed = titles[::group_size]
    return condensed[:MAX_CHAPTERS]


def _derive_chapter_titles_from_master_content(content: MasterContent) -> list[str]:
    """NotebookLM 챕터가 없을 때, MasterContent.analysis에 실제로 있는
    구조(causal_chain/bull_case/risks 등)만 근거로 챕터 제목을 만든다.
    비어 있는 섹션은 지어내지 않고 건너뛴다.
    """
    analysis = content.analysis
    titles = ["핵심 답변"]
    if content.market_data.macro_events or analysis.facts:
        titles.append("무슨 일이 있었나")
    if analysis.causal_chain or analysis.market_implications:
        titles.append("시장에 전달되는 경로")
    if analysis.bull_case or analysis.bear_case:
        titles.append("긍정과 위험 요인")
    if analysis.risks:
        titles.append("주요 리스크")
    if analysis.update_triggers:
        titles.append("앞으로 확인할 지표")
    titles.append("핵심 요약")
    return titles


def _generate_chapter_candidates(content: MasterContent) -> list[YoutubeChapter]:
    """content.youtube.chapters가 비어 있을 때(현재 항상 그렇다 -
    YouTubeOutput 자체는 챕터를 생성하지 않는다) NotebookLM 스크립트의
    chapters(있으면 우선 - --generate-all/--notebooklm --youtube 조합
    실행 시 이미 채워져 있다)나, 없으면 MasterContent.analysis 구조를
    바탕으로 4~7개의 챕터 후보를 만든다.

    실제 영상 편집 전이라 정확한 타임스탬프는 알 수 없다. 여기서 붙이는
    타임스탬프는 NotebookLM 목표 분량(4~7분) 중간값을 균등 배분한
    "예상" 값이며, 실제 편집 후 다시 맞춰야 하는 후보다(빈 챕터
    목록보다는 실무에서 바로 다듬어 쓸 수 있는 출발점을 준다).
    """
    if content.notebooklm.chapters:
        titles = _condense_to_chapter_titles(list(content.notebooklm.chapters))
    else:
        titles = _condense_to_chapter_titles(_derive_chapter_titles_from_master_content(content))

    if not titles:
        return []

    interval = _ASSUMED_VIDEO_SECONDS // len(titles)
    return [
        YoutubeChapter(timestamp=_format_timestamp(i * interval), title=title)
        for i, title in enumerate(titles)
    ]


def generate_youtube_output(
    content: MasterContent,
    *,
    llm_client: LlmClient | None = None,
    usage_log: list[dict] | None = None,
) -> MasterContent:
    """MasterContent.market_data/analysis를 근거로 youtube 필드를 채운다
    (실제 Anthropic Claude 기반 생성).

    응답이 JSON으로 파싱되지 않거나 YouTubeOutput 스키마와 맞지 않으면,
    같은 요청을 무한 반복하지 않고 최대 1회(schema-repair 프롬프트로)만
    다시 시도한다. 두 번째 시도도 실패하면 YoutubeGenerationError를
    던진다(호출부인 pipeline/multi_channel.py가 이 채널만 FAIL로
    기록하고 나머지 채널은 계속 생성한다).
    """
    client = llm_client or LlmClient()
    user_prompt = _build_user_prompt(content)

    output: YouTubeOutput | None = None
    last_error: Exception | None = None

    for attempt, system_prompt in enumerate((_SYSTEM_PROMPT, _REPAIR_SYSTEM_PROMPT), start=1):
        raw_response, usage = client.generate_with_usage(
            user_prompt,
            system_prompt=system_prompt,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        if usage_log is not None:
            usage_log.append(
                {
                    "provider": "anthropic",
                    "model": getattr(client, "model", ""),
                    "channel": "youtube",
                    "attempt": attempt,
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                }
            )

        try:
            output = _parse_and_build(raw_response)
            break
        except YoutubeGenerationError as exc:
            last_error = exc
            logger.warning(
                "YouTube 채널 구조화 출력 파싱/검증 실패(시도 %d/%d): %s",
                attempt, MAX_ATTEMPTS, exc,
            )

    if output is None:
        raise YoutubeGenerationError(
            f"YouTube 구조화 출력 생성에 최종 실패했습니다"
            f"(원 시도 1회 + schema-repair 재시도 1회, 총 {MAX_ATTEMPTS}회). "
            f"마지막 오류: {last_error}"
        )

    combined_text = "\n\n".join([output.recommended_title, output.description, output.pinned_comment])

    try:
        check_for_hallucinated_numbers(combined_text, content)
    except HallucinationDetectedError as exc:
        raise YoutubeGenerationError(str(exc)) from exc

    fact_result = validate_text_grounding(combined_text, output.used_fact_ids, content)
    if fact_result.status == FactValidationStatus.FAIL:
        raise YoutubeFactGroundingError(fact_result)

    content.youtube = YoutubeMeta(
        title=output.recommended_title,
        title_candidates=output.title_candidates,
        description=output.description,
        chapters=_generate_chapter_candidates(content),
        pinned_comment=output.pinned_comment,
        tags=output.tags,
        fact_validation_status=fact_result.status.value,
        fact_validation_warnings=fact_result.warnings,
        used_fact_ids=fact_result.used_fact_ids,
        generated_at=output.generated_at,
    )
    content.touch()
    return content
