"""8단계: 같은 MasterContent로 YouTube 제목/설명/태그/고정댓글 생성.

generate_youtube_meta() (기존, placeholder)는 pipeline/orchestrator.py의
단일 WordPress 파이프라인이 계속 쓰므로 그대로 남겨 두었다.

generate_youtube_output() (신규)이 실제 Anthropic Claude 기반 생성이다.
pipeline/multi_channel.py의 새 다채널 생성 파이프라인이 이 함수를 쓴다.
WordPressArticle을 거치지 않고 MasterContent.market_data/analysis를
직접 입력받는다.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from clients.llm_client import LlmClient
from modules.master_content.schema import MasterContent, YoutubeChapter, YoutubeMeta
from modules.shared_grounding.fact_validation import FactValidationStatus, validate_text_grounding
from modules.shared_grounding.generation_support import (
    GenerationParsingError,
    HallucinationDetectedError,
    check_for_hallucinated_numbers,
    parse_llm_json,
)

from .models import YouTubeOutput

DEFAULT_MAX_TOKENS = 2048


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

[출력 형식]
다른 설명, 코드펜스, 부가 텍스트 없이 아래 키를 가진 JSON 객체 하나만
출력한다.

{
  "title_candidates": string[],
  "recommended_title": string,
  "description": string,
  "tags": string[],
  "pinned_comment": string,
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


def generate_youtube_output(
    content: MasterContent,
    *,
    llm_client: LlmClient | None = None,
    usage_log: list[dict] | None = None,
) -> MasterContent:
    """MasterContent.market_data/analysis를 근거로 youtube 필드를 채운다
    (실제 Anthropic Claude 기반 생성).
    """
    client = llm_client or LlmClient()

    raw_response, usage = client.generate_with_usage(
        _build_user_prompt(content),
        system_prompt=_SYSTEM_PROMPT,
        max_tokens=DEFAULT_MAX_TOKENS,
    )
    if usage_log is not None:
        usage_log.append(
            {
                "provider": "anthropic",
                "model": getattr(client, "model", ""),
                "channel": "youtube",
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        )

    try:
        data = parse_llm_json(raw_response)
    except GenerationParsingError as exc:
        raise YoutubeGenerationError(str(exc)) from exc

    output = _build_output(data)

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
