"""7단계: 같은 MasterContent로 NotebookLM 영상 원고 생성.

generate_notebooklm_script() (기존, placeholder)는 pipeline/orchestrator.py
의 단일 WordPress 파이프라인이 계속 쓰므로 그대로 남겨 두었다.

generate_notebooklm_output() (신규)이 실제 Anthropic Claude 기반 생성이다.
pipeline/multi_channel.py의 새 다채널 생성 파이프라인이 이 함수를 쓴다.
WordPressArticle을 거치지 않고 MasterContent.market_data/analysis를
직접 입력받는다.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from clients.llm_client import LlmClient
from modules.master_content.schema import MasterContent, NotebookLmContent
from modules.shared_grounding.fact_validation import FactValidationStatus, validate_text_grounding
from modules.shared_grounding.generation_support import (
    GenerationParsingError,
    HallucinationDetectedError,
    check_for_hallucinated_numbers,
    parse_llm_json,
)

from .models import NotebookLmScriptOutput

DEFAULT_MAX_TOKENS = 4096


class NotebookLmGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


class NotebookLmFactGroundingError(NotebookLmGenerationError):
    """Fact Grounding 검증이 FAIL 판정을 내렸을 때 발생한다."""

    def __init__(self, result) -> None:  # noqa: ANN001
        self.result = result
        parts = ["NotebookLM Fact Grounding 검증 실패(FAIL)."]
        if result.invalid_fact_ids:
            parts.append(f"존재하지 않는 Fact ID: {result.invalid_fact_ids}")
        if result.unsupported_numbers:
            parts.append(f"근거 없는 수치/날짜: {result.unsupported_numbers}")
        super().__init__(" ".join(parts))


def generate_notebooklm_script(content: MasterContent) -> MasterContent:
    """기존 placeholder 구현(변경하지 않음). wordpress 콘텐츠를 그대로 읽는다."""
    wp = content.wordpress
    script = (
        f"오늘의 주제는 '{wp.title}' 입니다.\n\n"
        f"{wp.excerpt}\n\n"
        "지금부터 자세한 내용을 살펴보겠습니다."
    )

    content.notebooklm = NotebookLmContent(script=script)
    content.touch()
    return content


_SYSTEM_PROMPT = """당신은 "돈맥" 매체의 영상 원고 작가다. Google NotebookLM
같은 AI 영상화 도구에 그대로 넣을 수 있는 한국어 원고를 쓴다.

[가장 중요한 규칙 - Anti-Hallucination]
제공된 MasterContent만 사실의 근거로 사용한다.
MasterContent에 없는 숫자, 날짜, 인물 발언, 정책 내용, 시장 가격을
만들어내지 않는다.

[문체 규칙]
- 글이 아니라 말하듯 자연스럽게 쓴다.
- 문장을 짧게 쓴다. 음성으로 읽었을 때 부자연스러운 괄호/기호는
  최소화한다.
- 숫자는 듣기 쉽게 표현한다(예: "300억 달러"처럼 발음하기 쉬운 단위로).
- 같은 숫자를 반복해서 말하지 않는다.
- "그래서", "여기서 중요한 건" 같은 연결어는 필요할 때만 적절히 쓴다.
- 과도한 유튜브식 과장(감탄사 남발, 클릭베이트 어투)을 쓰지 않는다.
- WordPress 본문을 그대로 읽는 형식이 아니다 - 영상으로 들을 때
  자연스러운 새 원고를 쓴다.

[구조]
전체 script 안에 아래 9개 구간을 순서대로 담되, 자연스러운 말로
이어지게 쓴다(구간 제목을 본문에 그대로 노출하지 않아도 된다).
1. Hook(주의를 끄는 첫 문장)
2. 사건 설명
3. 어려운 개념을 쉽게 설명
4. 돈의 흐름/전달 경로
5. 채권시장
6. 주식시장
7. 반대로 볼 수 있는 시나리오
8. 앞으로 볼 지표
9. 2~3문장 결론
chapters 필드에는 이 9개 구간의 제목(또는 실제로 다룬 구간 제목)을
순서대로 넣는다. 전체 분량은 약 4~7분 분량(말하는 속도 기준 대략
600~1,100자 사이)을 목표로 하되, 정보가 부족한 주제는 억지로 늘리지
않는다.

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다.
스크립트에서 구체적인 수치/날짜/주장의 근거로 사용한 fact의 id를 모두
used_fact_ids 배열에 넣는다. facts 목록에 없는 id를 지어내지 않는다.

[출력 형식]
다른 설명, 코드펜스, 부가 텍스트 없이 아래 키를 가진 JSON 객체 하나만
출력한다.

{
  "title": string,
  "hook": string,
  "script": string,
  "chapters": string[],
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
        "다음은 이번 영상 원고 작성에 사용할 MasterContent(JSON)이다. "
        "이 안에 있는 정보만 사실의 근거로 사용하라.\n\n"
        f"```json\n{master_content_json}\n```\n\n"
        "위 MasterContent만 근거로 삼아 영상 원고를 시스템 프롬프트의 "
        "JSON 스키마에 맞춰 작성하라."
    )


def _build_output(data: dict) -> NotebookLmScriptOutput:
    try:
        return NotebookLmScriptOutput.model_validate(data)
    except ValidationError as exc:
        raise NotebookLmGenerationError(
            f"LLM 응답이 NotebookLmScriptOutput 스키마와 맞지 않습니다: {exc}"
        ) from exc


def generate_notebooklm_output(
    content: MasterContent,
    *,
    llm_client: LlmClient | None = None,
    usage_log: list[dict] | None = None,
) -> MasterContent:
    """MasterContent.market_data/analysis를 근거로 notebooklm 필드를 채운다
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
                "channel": "notebooklm",
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        )

    try:
        data = parse_llm_json(raw_response)
    except GenerationParsingError as exc:
        raise NotebookLmGenerationError(str(exc)) from exc

    output = _build_output(data)

    try:
        check_for_hallucinated_numbers(output.script, content)
    except HallucinationDetectedError as exc:
        raise NotebookLmGenerationError(str(exc)) from exc

    fact_result = validate_text_grounding(output.script, output.used_fact_ids, content)
    if fact_result.status == FactValidationStatus.FAIL:
        raise NotebookLmFactGroundingError(fact_result)

    content.notebooklm = NotebookLmContent(
        script=output.script,
        title=output.title,
        hook=output.hook,
        chapters=output.chapters,
        fact_validation_status=fact_result.status.value,
        fact_validation_warnings=fact_result.warnings,
        used_fact_ids=fact_result.used_fact_ids,
        generated_at=output.generated_at,
    )
    content.touch()
    return content
