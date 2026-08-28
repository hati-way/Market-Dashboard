"""9단계: 같은 MasterContent로 썸네일 문구/Midjourney 프롬프트 생성.

generate_thumbnail_assets() (기존, placeholder)는 pipeline/orchestrator.py
의 단일 WordPress 파이프라인이 계속 쓰므로 그대로 남겨 두었다.

generate_thumbnail_output() (신규)이 실제 Anthropic Claude 기반 생성이다.
pipeline/multi_channel.py의 새 다채널 생성 파이프라인이 이 함수를 쓴다.
WordPressArticle을 거치지 않고 MasterContent.market_data/analysis를
직접 입력받는다.

이미지는 시스템이 직접 생성하지 않는다 - Midjourney 등에서 쓸 프롬프트
텍스트만 만든다.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from clients.llm_client import LlmClient
from modules.master_content.schema import MasterContent, ThumbnailAssets
from modules.shared_grounding.fact_validation import FactValidationStatus, validate_text_grounding
from modules.shared_grounding.generation_support import (
    GenerationParsingError,
    HallucinationDetectedError,
    check_for_hallucinated_numbers,
    parse_llm_json,
)

from .models import ThumbnailOutput

DEFAULT_MAX_TOKENS = 2048


class ThumbnailGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


class ThumbnailFactGroundingError(ThumbnailGenerationError):
    """Fact Grounding 검증이 FAIL 판정을 내렸을 때 발생한다."""

    def __init__(self, result) -> None:  # noqa: ANN001
        self.result = result
        parts = ["Thumbnail Fact Grounding 검증 실패(FAIL)."]
        if result.invalid_fact_ids:
            parts.append(f"존재하지 않는 Fact ID: {result.invalid_fact_ids}")
        if result.unsupported_numbers:
            parts.append(f"근거 없는 수치/날짜: {result.unsupported_numbers}")
        super().__init__(" ".join(parts))


def generate_thumbnail_assets(content: MasterContent) -> MasterContent:
    """기존 placeholder 구현(변경하지 않음). 주제를 영어 프롬프트 템플릿에 끼워 넣는다."""
    topic = content.meta.topic or content.wordpress.title

    midjourney_prompt = (
        f"finance news thumbnail, topic: {topic}, "
        "bold modern typography, dark blue and neon accent colors, "
        "stock market chart background, high contrast, 16:9 --ar 16:9"
    )
    canva_text = topic

    content.thumbnail = ThumbnailAssets(
        midjourney_prompt=midjourney_prompt,
        canva_text=canva_text,
    )
    content.touch()
    return content


_SYSTEM_PROMPT = """당신은 "돈맥" 매체의 유튜브 썸네일 카피라이터 겸
Midjourney 프롬프트 작가다.

[가장 중요한 규칙 - Anti-Hallucination]
제공된 MasterContent만 사실의 근거로 사용한다. thumbnail_text_candidates/
recommended_text에는 MasterContent에 없는 숫자, 날짜, 정책 내용을
만들어내지 않는다.

[썸네일 문구 규칙]
- 후보 5개를 만들고, 그중 하나를 recommended_text로 고른다.
- 2~7단어 수준으로 짧게 쓴다. 모바일 화면에서도 바로 읽혀야 한다.
- 글 제목을 그대로 반복하지 않는다.
- 숫자는 핵심일 때만 사용한다.
- 공포성 과장을 쓰지 않는다.
- 예: "미국은 왜 국채를 다시 살까", "300억 달러의 신호"

[Midjourney 프롬프트 규칙]
- 16:9 비율을 명시한다.
- 텍스트를 이미지 안에 생성시키지 않는다(문구는 나중에 Canva에서
  얹는다) - "no text", "no typography" 같은 표현을 포함한다.
- 금융 차트/달러/국채 같은 클리셰 이미지를 과도하게 쓰지 않는다.
- 경제 흐름을 상징적으로 보여주는 editorial visual, high contrast
  composition으로 묘사한다.
- 피사체가 작게 보이지 않도록 명시한다(예: "subject fills the frame",
  "not too small in frame").
- 사람이 등장하면 실존 정치인을 직접 묘사하지 않아도 되며, 상징적인
  장면을 우선한다(예: 실루엣, 손, 문서, 건물 등).
- avoid_elements에는 이번 이미지에서 피해야 할 요소(예: 특정 클리셰,
  과도한 텍스트, 실존 인물 얼굴 등)를 나열한다.
- visual_concept에는 이 이미지가 전달하려는 한 문장짜리 컨셉을 쓴다.

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다.
thumbnail_text_candidates/recommended_text에서 구체적인 수치의 근거로
사용한 fact의 id를 모두 used_fact_ids 배열에 넣는다. facts 목록에 없는
id를 지어내지 않는다.

[출력 형식]
다른 설명, 코드펜스, 부가 텍스트 없이 아래 키를 가진 JSON 객체 하나만
출력한다.

{
  "thumbnail_text_candidates": string[],
  "recommended_text": string,
  "midjourney_prompt": string,
  "visual_concept": string,
  "avoid_elements": string[],
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
        "다음은 이번 썸네일 문구/프롬프트 작성에 사용할 MasterContent(JSON)이다. "
        "이 안에 있는 정보만 사실의 근거로 사용하라.\n\n"
        f"```json\n{master_content_json}\n```\n\n"
        "위 MasterContent만 근거로 삼아 썸네일 산출물을 시스템 프롬프트의 "
        "JSON 스키마에 맞춰 작성하라."
    )


def _build_output(data: dict) -> ThumbnailOutput:
    try:
        return ThumbnailOutput.model_validate(data)
    except ValidationError as exc:
        raise ThumbnailGenerationError(
            f"LLM 응답이 ThumbnailOutput 스키마와 맞지 않습니다: {exc}"
        ) from exc


def generate_thumbnail_output(
    content: MasterContent,
    *,
    llm_client: LlmClient | None = None,
    usage_log: list[dict] | None = None,
) -> MasterContent:
    """MasterContent.market_data/analysis를 근거로 thumbnail 필드를 채운다
    (실제 Anthropic Claude 기반 생성).

    Fact Grounding은 실제 문구(thumbnail_text_candidates/recommended_text)
    에만 적용한다 - midjourney_prompt/visual_concept은 이미지 생성용
    영어 묘사문이라 사실 주장이 아니다.
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
                "channel": "thumbnail",
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        )

    try:
        data = parse_llm_json(raw_response)
    except GenerationParsingError as exc:
        raise ThumbnailGenerationError(str(exc)) from exc

    output = _build_output(data)

    text_only = "\n".join([*output.thumbnail_text_candidates, output.recommended_text])

    try:
        check_for_hallucinated_numbers(text_only, content)
    except HallucinationDetectedError as exc:
        raise ThumbnailGenerationError(str(exc)) from exc

    fact_result = validate_text_grounding(text_only, output.used_fact_ids, content)
    if fact_result.status == FactValidationStatus.FAIL:
        raise ThumbnailFactGroundingError(fact_result)

    content.thumbnail = ThumbnailAssets(
        midjourney_prompt=output.midjourney_prompt,
        canva_text=output.recommended_text,
        thumbnail_text_candidates=output.thumbnail_text_candidates,
        visual_concept=output.visual_concept,
        avoid_elements=output.avoid_elements,
        fact_validation_status=fact_result.status.value,
        fact_validation_warnings=fact_result.warnings,
        used_fact_ids=fact_result.used_fact_ids,
        generated_at=output.generated_at,
    )
    content.touch()
    return content
