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
import re

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

# title/hook/script/chapters처럼 사용자에게 그대로 노출되는 필드에 내부
# Fact ID(예: "fact_004")가 섞여 나오면 안 된다(youtube_meta/
# threads_writer와 동일한 원칙. 채널 간 로직을 공유하지 않으므로 이
# 파일에도 독립적으로 둔다).
_INTERNAL_ID_RE = re.compile(r"\bfact_[a-z0-9]+\b", re.IGNORECASE)


class NotebookLmGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


class NotebookLmInternalIdLeakError(NotebookLmGenerationError):
    """title/hook/script/chapters에 내부 fact id가 그대로 섞여 나왔을 때 발생한다.

    fact_004 같은 식별자는 used_fact_ids 배열에만 담겨야 하는 내부
    bookkeeping 값이다.
    """


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

[내부 식별자 노출 금지]
MasterContent.analysis.facts의 각 항목에는 "fact_001"처럼 내부용 id가
있다. 이 id는 오직 used_fact_ids 배열에만 넣는다. title, hook, script,
chapters 어디에도 "fact_001" 같은 식별자 문자열을 절대 쓰지 않는다.

[문체 규칙 - 반드시 지킬 것]
- 글이 아니라 말하듯 자연스럽게 쓴다. WordPress 리포트를 소리 내어
  읽는 듯한 문체를 절대 쓰지 않는다("~로 나타났다", "~라고 밝혔다",
  "~을 시사한다" 같은 보고서 말투를 쓰지 않는다).
- 한 문장은 짧게 쓴다. 한 문장에는 원칙적으로 하나의 정보만 담는다 -
  두 가지 사실을 접속사로 길게 이어붙이지 않는다.
- 긴 문단을 피한다. 음성으로 읽었을 때 자연스럽게 숨을 쉴 수 있도록
  두세 문장마다 줄을 바꾼다.
- 숫자는 듣기 쉽게 표현한다(예: "300억 달러"처럼 발음하기 쉬운 단위로).
- 같은 숫자를 반복해서 말하지 않는다.
- "그래서", "여기서 중요한 건", "그런데" 같은 연결어는 자연스러울 때만
  쓰고, 스크립트 전체에서 같은 표현을 반복하지 않는다(다양하게 섞어
  쓴다).
- 과도한 유튜브식 과장(감탄사 남발, 클릭베이트 어투)을 쓰지 않는다.

[Hook - 첫 20~30초]
Hook은 단순히 사건을 소개하는 문장이 아니다. 다음 순서를 우선
따른다.
  핵심 숫자/사건 → 의외의 시장 반응 → 질문
예: "재무부가 국채를 300억 달러어치 다시 사들였습니다. 그런데 금리는
오히려 내려갔습니다. 왜 그랬을까요?"
첫 20~30초(말하는 속도 기준 대략 50~80자) 안에 시청자가 "왜 이
영상을 봐야 하는지" 알 수 있어야 한다.

[어려운 개념 설명 순서]
전문용어를 먼저 정의하지 않는다. 쉬운 현상이나 비유로 먼저 설명한
다음에 용어를 붙인다.
나쁜 예: "바이백이란 재무부가 시중의 국채를 다시 사들이는 정책입니다."
좋은 예: "정부가 예전에 판 채권을 시장에서 다시 사들이는 겁니다.
이걸 바이백이라고 부릅니다."

[구조]
전체 script 안에 아래 9개 구간을 순서대로 담되, 자연스러운 말로
이어지게 쓴다(구간 제목을 본문에 그대로 노출하지 않아도 된다).
1. Hook(위 [Hook] 규칙을 따른다)
2. 사건 설명
3. 어려운 개념을 쉽게 설명(위 [어려운 개념 설명 순서]를 따른다)
4. 돈의 흐름/전달 경로
5. 채권시장
6. 주식시장
7. 반대로 볼 수 있는 시나리오
8. 앞으로 볼 지표 + 방향별 해석(아래 [마지막 30초] 참고)
9. 결론(아래 [결론] 참고)
chapters 필드에는 이 9개 구간의 제목(또는 실제로 다룬 구간 제목)을
순서대로 넣는다.

[결론]
결론은 단순 요약이 아니다. "그래서 앞으로 무엇을 확인해야 하는가"에
집중한다.

[마지막 30초 - 확인 지표]
스크립트의 마지막 30초 정도는 다음을 명확히 설명한다.
- 앞으로 확인할 지표(예: 다음 QRA, 차기 바이백 운영 일정, 장기채 발행
  구조 등 - MasterContent.analysis.update_triggers에 실제로 있는
  것만 쓴다)
- 그 지표가 어느 방향으로 나오면 지금까지의 해석이 강화되는지, 어느
  방향이면 약화되는지를 함께 설명한다.
예: "다음 QRA에서 바이백 규모가 더 커지면 지금 해석에 힘이 실립니다.
반대로 규모가 줄어들면 오늘 설명한 흐름은 다시 봐야 합니다."

[저확신도 정보]
confidence가 low이거나 source_type이 secondary(예: "시장 컨센서스")
인 내용은 "일부 시장에서는 ~라고 봅니다", "한 가지 해석은 ~입니다"
처럼 반드시 제한적으로 표현한다. 확정적으로 말하지 않는다.

[분량]
전체 분량은 약 4~6분 분량(말하는 속도 기준 대략 600~950자 사이)을
우선 목표로 한다. 정보가 부족한 주제는 억지로 7분을 채우지 않는다.

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다.
스크립트에서 구체적인 수치/날짜/주장의 근거로 사용한 fact의 id를 모두
used_fact_ids 배열에 넣는다. facts 목록에 없는 id를 지어내지 않는다.
(다시 강조: 이 id를 title/hook/script/chapters 본문에는 절대 쓰지
않는다.)

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


def _check_no_internal_ids_leaked(output: NotebookLmScriptOutput) -> None:
    """title/hook/script/chapters처럼 사용자에게 노출되는 필드에 내부
    fact id(예: "fact_004")가 그대로 섞여 있으면 막는다. used_fact_ids
    필드 자체는 검사 대상이 아니다(거기엔 정당하게 id가 들어간다).
    """
    user_facing_fields: dict[str, str] = {
        "title": output.title,
        "hook": output.hook,
        "script": output.script,
    }
    for i, chapter in enumerate(output.chapters):
        user_facing_fields[f"chapters[{i}]"] = chapter

    leaked = {
        field: sorted(set(_INTERNAL_ID_RE.findall(text)))
        for field, text in user_facing_fields.items()
        if _INTERNAL_ID_RE.search(text)
    }
    if leaked:
        details = "; ".join(f"{field}={ids}" for field, ids in leaked.items())
        raise NotebookLmInternalIdLeakError(
            f"사용자에게 노출되는 필드에 내부 fact id가 섞여 있습니다: {details}"
        )


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
    _check_no_internal_ids_leaked(output)

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
