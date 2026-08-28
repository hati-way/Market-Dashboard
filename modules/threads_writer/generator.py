"""6단계: 같은 MasterContent로 Threads 글 생성.

generate_threads_content() (기존, placeholder)는 pipeline/orchestrator.py
의 단일 WordPress 파이프라인이 계속 쓰므로 그대로 남겨 두었다(이번
라운드에서 기존 WordPress 파이프라인을 건드리지 않기 위함).

generate_threads_output() (신규)이 실제 Anthropic Claude 기반 생성이다.
pipeline/multi_channel.py의 새 다채널 생성 파이프라인이 이 함수를 쓴다.
WordPressArticle을 거치지 않고 MasterContent.market_data/analysis를
직접 입력받는다(WordPress의 해석 오류/문체가 다른 채널로 전파되는 것을
막기 위함, CLAUDE.md 원칙).
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from clients.llm_client import LlmClient
from modules.master_content.schema import MasterContent, ThreadsContent, ThreadsPost
from modules.shared_grounding.fact_validation import FactValidationStatus, validate_text_grounding
from modules.shared_grounding.generation_support import (
    GenerationParsingError,
    HallucinationDetectedError,
    check_for_hallucinated_numbers,
    parse_llm_json,
)

from .models import ThreadsOutput

THREADS_MAX_LENGTH = 500
DEFAULT_MAX_TOKENS = 2048

# posts/hook/key_message처럼 사용자에게 그대로 노출되는 필드에 내부
# Fact ID(예: "fact_004")가 그대로 섞여 나오면 안 된다(youtube_meta의
# 동일한 원칙 - modules/youtube_meta/generator.py 참고. 채널 간 로직을
# 공유하지 않으므로 이 파일에도 독립적으로 둔다).
_INTERNAL_ID_RE = re.compile(r"\bfact_[a-z0-9]+\b", re.IGNORECASE)


class ThreadsGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


class ThreadsInternalIdLeakError(ThreadsGenerationError):
    """posts/hook/key_message에 내부 fact id가 그대로 섞여 나왔을 때 발생한다.

    fact_004 같은 식별자는 used_fact_ids 배열에만 담겨야 하는 내부
    bookkeeping 값이다.
    """


class ThreadsFactGroundingError(ThreadsGenerationError):
    """Fact Grounding 검증이 FAIL 판정을 내렸을 때 발생한다."""

    def __init__(self, result) -> None:  # noqa: ANN001 - FactValidationResult, 순환 임포트 방지 위해 지연 타이핑
        self.result = result
        parts = ["Threads Fact Grounding 검증 실패(FAIL)."]
        if result.invalid_fact_ids:
            parts.append(f"존재하지 않는 Fact ID: {result.invalid_fact_ids}")
        if result.unsupported_numbers:
            parts.append(f"근거 없는 수치/날짜: {result.unsupported_numbers}")
        super().__init__(" ".join(parts))


def generate_threads_content(content: MasterContent) -> MasterContent:
    """기존 placeholder 구현(변경하지 않음). wordpress.excerpt를 재활용한다."""
    summary = content.wordpress.excerpt or content.wordpress.title
    text = summary[:THREADS_MAX_LENGTH]

    content.threads = ThreadsContent(posts=[ThreadsPost(text=text, order=1)])
    content.touch()
    return content


_SYSTEM_PROMPT = """당신은 "돈맥" 매체의 Threads(소셜) 라이터다.
WordPress 리서치 글을 요약하는 사람이 아니다 - Threads 전용으로
완전히 새로 쓴다. 리포트/기사를 짧게 줄인 듯한 문장이 하나라도 있으면
안 된다.

[가장 중요한 규칙 - Anti-Hallucination]
제공된 MasterContent만 사실의 근거로 사용한다.
MasterContent에 없는 숫자, 날짜, 인물 발언, 정책 내용, 시장 가격을
만들어내지 않는다. 숫자와 사실 자체는 그대로 유지하되, 그 숫자를
설명하는 말은 압축한다.

[내부 식별자 노출 금지]
MasterContent.analysis.facts의 각 항목에는 "fact_001"처럼 내부용 id가
있다. 이 id는 오직 used_fact_ids 배열에만 넣는다. posts, hook,
key_message 어디에도 "fact_001" 같은 식별자 문자열을 절대 쓰지 않는다.

[문체 규칙 - 반드시 지킬 것]
- 평어(반말체 아닌, 정보를 전달하는 짧은 서술문)를 쓴다.
- 한 문장은 짧게 쓴다. 한 문장에 두 가지 이상을 욱여넣지 않는다.
- 기사체/리포트체를 절대 쓰지 않는다("~로 나타났다", "~라고 밝혔다",
  "~을 시사한다", "~것으로 보인다" 같은 보고서 말투 금지).
- 경제를 잘 모르는 사람도 따라올 수 있게 쓴다. 전문용어는 풀어서
  설명한다.
- 인과관계를 보여줄 때는 가능하면 "→"를 써서 흐름을 시각적으로
  보여준다(예: "바이백 확대 → 유동성 개선 → 금리 변동성 완화"). 다만
  단정적인 인과가 아니라 실제로 그렇게 될 수 있다는 흐름일 때만 쓴다.
- "중요한 건", "그런데", "그래서", "앞으로 볼 건" 같은 자연스러운
  연결어를 실제로 문장 사이에 쓴다. 문장을 그냥 나열하지 않는다.
- 이모지는 기본적으로 쓰지 않는다.
- 다음 표현을 쓰지 않는다: "제공된 자료에 따르면", "본 분석에서는",
  "결론적으로", 반복적인 "가능성이 있다", 기사체 헤드라인 나열,
  WordPress 본문을 그대로 줄인 듯한 설명형 문장.
- confidence가 low이거나 source_type이 secondary(예: "시장 컨센서스")
  인 내용은 "일부 시장에서는 ~라고 본다", "일부 시장 참여자는 ~라고
  본다"처럼 제한적으로만 표현한다. 확정적으로 쓰지 않는다.

[구조 - 각 post는 하나의 메시지만]
post는 기본 4개로 구성한다(정보가 아주 많거나 적을 때만 3~5개 사이로
조정한다). 각 post는 "현재번호/전체개수 "로 시작하는 실제 텍스트를
포함한다(예: 4개 구성이면 "1/4 ", "2/4 ", "3/4 ", "4/4 "). 번호 뒤에
공백을 하나 넣는다. 각 post는 오직 하나의 메시지만 전달한다 - 여러
주제를 한 post에 섞지 않는다.

1. 첫 post(hook): 2~4개의 짧은 문장으로 궁금증을 만든다. 핵심 사건과
   왜 지금 중요한지를 짧게 던지고, 다음 post에서 풀어갈 것처럼
   마무리한다. 과도한 클릭베이트는 쓰지 않는다.
2. 두 번째 post: 자금/유동성/금리가 전달되는 경로를 짧게 설명한다.
   가능하면 "→" 흐름을 쓴다.
3. 세 번째 post: 시장 영향 또는 반대로 봐야 할 시나리오 중 하나를
   짧게 다룬다(둘 다 넣지 않는다 - 한 post는 하나의 메시지만).
4. 마지막 post: 앞으로 확인할 지표를 짧게 언급하고, 마지막 한 줄로
   결론을 압축한다.
정보가 부족한 주제는 post 수를 줄인다(최소 3개). 절대 억지로 늘리지
않는다.

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다.
본문에서 구체적인 수치/날짜/주장의 근거로 사용한 fact의 id를 모두
used_fact_ids 배열에 넣는다. facts 목록에 없는 id를 지어내지 않는다.
(다시 강조: 이 id를 post 본문에는 절대 쓰지 않는다.)

[출력 형식]
다른 설명, 코드펜스, 부가 텍스트 없이 아래 키를 가진 JSON 객체 하나만
출력한다.

{
  "posts": string[],
  "hook": string,
  "key_message": string,
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
        "다음은 이번 Threads 글 작성에 사용할 MasterContent(JSON)이다. "
        "이 안에 있는 정보만 사실의 근거로 사용하라.\n\n"
        f"```json\n{master_content_json}\n```\n\n"
        "위 MasterContent만 근거로 삼아 Threads 글을 시스템 프롬프트의 "
        "JSON 스키마에 맞춰 작성하라."
    )


def _build_output(data: dict) -> ThreadsOutput:
    try:
        return ThreadsOutput.model_validate(data)
    except ValidationError as exc:
        raise ThreadsGenerationError(
            f"LLM 응답이 ThreadsOutput 스키마와 맞지 않습니다: {exc}"
        ) from exc


def _check_no_internal_ids_leaked(output: ThreadsOutput) -> None:
    """posts/hook/key_message처럼 사용자에게 노출되는 필드에 내부 fact
    id(예: "fact_004")가 그대로 섞여 있으면 막는다. used_fact_ids
    필드 자체는 검사 대상이 아니다(거기엔 정당하게 id가 들어간다).
    """
    user_facing_fields: dict[str, str] = {"hook": output.hook, "key_message": output.key_message}
    for i, post in enumerate(output.posts):
        user_facing_fields[f"posts[{i}]"] = post

    leaked = {
        field: sorted(set(_INTERNAL_ID_RE.findall(text)))
        for field, text in user_facing_fields.items()
        if _INTERNAL_ID_RE.search(text)
    }
    if leaked:
        details = "; ".join(f"{field}={ids}" for field, ids in leaked.items())
        raise ThreadsInternalIdLeakError(
            f"사용자에게 노출되는 필드에 내부 fact id가 섞여 있습니다: {details}"
        )


def generate_threads_output(
    content: MasterContent,
    *,
    llm_client: LlmClient | None = None,
    usage_log: list[dict] | None = None,
) -> MasterContent:
    """MasterContent.market_data/analysis를 근거로 threads 필드를 채운다
    (실제 Anthropic Claude 기반 생성).

    llm_client를 넘기지 않으면 실제 Anthropic API를 호출하는
    LlmClient()를 새로 만든다(테스트에서는 가짜 client를 주입한다).
    usage_log를 넘기면 이번 호출의 token usage를 기록한 dict를
    append한다(비용 추적용, 선택 사항).
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
                "channel": "threads",
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        )

    try:
        data = parse_llm_json(raw_response)
    except GenerationParsingError as exc:
        raise ThreadsGenerationError(str(exc)) from exc

    output = _build_output(data)
    _check_no_internal_ids_leaked(output)

    combined_text = "\n\n".join(output.posts)

    # 1차 방어선: 본문의 소수점 숫자가 MasterContent에 있는지 최소한으로 대조한다.
    try:
        check_for_hallucinated_numbers(combined_text, content)
    except HallucinationDetectedError as exc:
        raise ThreadsGenerationError(str(exc)) from exc

    # 2차 방어선: Fact ID + 퍼센트/bp/금액/날짜를 구조적으로 대조한다.
    fact_result = validate_text_grounding(combined_text, output.used_fact_ids, content)
    if fact_result.status == FactValidationStatus.FAIL:
        raise ThreadsFactGroundingError(fact_result)

    content.threads = ThreadsContent(
        posts=[ThreadsPost(text=post, order=i) for i, post in enumerate(output.posts, start=1)],
        hook=output.hook,
        key_message=output.key_message,
        fact_validation_status=fact_result.status.value,
        fact_validation_warnings=fact_result.warnings,
        used_fact_ids=fact_result.used_fact_ids,
        generated_at=output.generated_at,
    )
    content.touch()
    return content
