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


class YoutubeGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


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

[제목(title_candidates/recommended_title) 규칙]
- 후보 5개를 만들고, 그중 하나를 recommended_title로 고른다.
- 45~70자 권장.
- 사람의 궁금증을 유도하되 지나친 공포/탐욕 클릭베이트는 금지한다.
- 핵심 경제 키워드를 포함한다.
- 예: "미국이 국채를 다시 사들이는 이유, 300억 달러 바이백의 진짜 의미"

[설명(description) 구조]
- 첫 2줄에 영상의 핵심을 담는다.
- 이 영상이 무엇을 설명하는지 짧게 쓴다.
- 주요 포인트를 3~5개 나열한다.
- 출처를 명시한다(MasterContent의 sources/facts에 있는 기관명만 쓴다).
- 투자 권유가 아니라는 점을 한 줄로 짧게 명시할 수 있다.

[tags]
과도한 태그 나열을 하지 않는다(핵심 키워드 위주로 10개 이내를
권장한다).

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다.
설명/고정댓글에서 구체적인 수치/날짜/주장의 근거로 사용한 fact의 id를
모두 used_fact_ids 배열에 넣는다. facts 목록에 없는 id를 지어내지
않는다.

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
# "설명 없이 JSON object만" 을 강하게 재확인만 시킨다.
_REPAIR_SYSTEM_PROMPT = """직전 응답이 유효한 JSON object로 파싱되지 않았다.

지금부터 다시 시도한다. 이전 응답을 설명하거나 사과하지 않는다. 왜
실패했는지 언급하지 않는다. 다른 텍스트, 코드펜스, 마크다운, 주석 없이
오직 유효한 JSON object 하나만 출력한다. 응답의 첫 글자는 "{"이고
마지막 글자는 "}"여야 한다.

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


def _parse_and_build(raw_response: str) -> YouTubeOutput:
    data = _parse_youtube_json(raw_response)
    return _build_output(data)


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
        chapters=[],
        pinned_comment=output.pinned_comment,
        tags=output.tags,
        fact_validation_status=fact_result.status.value,
        fact_validation_warnings=fact_result.warnings,
        used_fact_ids=fact_result.used_fact_ids,
        generated_at=output.generated_at,
    )
    content.touch()
    return content
