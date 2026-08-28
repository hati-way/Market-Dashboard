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


class ThreadsGenerationError(Exception):
    """LLM 응답 파싱/검증에 실패했을 때 발생한다."""


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

[가장 중요한 규칙 - Anti-Hallucination]
제공된 MasterContent만 사실의 근거로 사용한다.
MasterContent에 없는 숫자, 날짜, 인물 발언, 정책 내용, 시장 가격을
만들어내지 않는다.

[문체 규칙]
- 평어(반말체 아닌, 정보를 전달하는 짧은 서술문)를 쓴다.
- 문장을 짧고 직접적으로 쓴다. 한 문장을 길게 늘이지 않는다.
- 경제를 잘 모르는 사람도 따라올 수 있게 쓴다. 전문용어는 풀어서
  설명한다.
- 첫 문장에서 궁금증을 만들되, 과도한 클릭베이트는 쓰지 않는다.
- 단순 뉴스 요약이 아니라 "그래서 돈이 어디로 흐를 수 있는가"를
  중심으로 쓴다.
- 이모지는 기본적으로 쓰지 않는다.
- 다음 표현을 쓰지 않는다: "제공된 자료에 따르면", "본 분석에서는",
  "결론적으로", 반복적인 "가능성이 있다", 기사체 헤드라인 나열.

[구조]
포스트는 3~5개로 구성한다(주제에 따라 유연하게). "1/N" 형태의 번호는
붙이지 않는다(시스템이 순서를 별도로 관리한다). 기본 흐름:
1. 핵심 사건 + 왜 지금 중요한지
2. 자금/유동성/금리가 전달되는 경로
3. 시장 영향 또는 반대로 봐야 할 시나리오
4. 앞으로 볼 지표 + 한 줄 결론
정보가 부족하면 포스트 수를 줄인다(최소 3개).

[Fact 인용]
사용자 메시지의 MasterContent.analysis.facts 각 항목에는 id가 있다.
본문에서 구체적인 수치/날짜/주장의 근거로 사용한 fact의 id를 모두
used_fact_ids 배열에 넣는다. facts 목록에 없는 id를 지어내지 않는다.

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
