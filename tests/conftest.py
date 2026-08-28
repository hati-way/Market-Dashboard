"""여러 테스트 파일이 공유하는 fixture/헬퍼.

wordpress_writer가 placeholder에서 실제 LlmClient.generate() 호출로
바뀌면서, 다른 모듈(threads_writer 등)을 독립적으로 테스트하던 기존
테스트들도 generate_wordpress_content() 를 거친다. 이때 실제 Anthropic
API를 부르지 않도록 가짜 LlmClient를 주입할 수 있게 해준다.
"""
import json

import pytest


class FakeLlmClient:
    """clients.llm_client.LlmClient 와 같은 generate()/generate_with_usage()
    인터페이스를 갖는 더미.

    실제 Anthropic API를 호출하지 않고 미리 정해둔 텍스트를 그대로
    돌려준다. 어떤 프롬프트로 호출되었는지 calls 에 기록해 두어, 필요하면
    테스트에서 프롬프트 내용을 검증할 수 있다.

    response_text(기존 방식, 하위 호환)를 주면 모든 호출에 항상 같은
    텍스트를 돌려준다. responses(신규)를 리스트로 주면 호출 순서대로
    하나씩 소비한다 - 한 MasterContent로 여러 채널(threads/notebooklm/
    youtube/thumbnail)을 순서대로 생성하는 통합 테스트에서, 채널마다
    다른 캔 응답을 넣어줄 때 쓴다.
    """

    def __init__(self, response_text: str | None = None, responses: list[str] | None = None):
        self.response_text = response_text
        self._responses = list(responses) if responses is not None else None
        self.calls: list[dict] = []

    def _next_response(self) -> str:
        if self._responses is not None:
            if not self._responses:
                raise AssertionError("FakeLlmClient: 준비된 응답을 모두 소진했습니다.")
            return self._responses.pop(0)
        return self.response_text

    def generate(self, user_prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        self.calls.append({"user_prompt": user_prompt, "system_prompt": system_prompt, **kwargs})
        return self._next_response()

    def generate_with_usage(
        self, user_prompt: str, system_prompt: str | None = None, **kwargs
    ) -> tuple[str, dict[str, int | None]]:
        text = self.generate(user_prompt, system_prompt, **kwargs)
        return text, {"input_tokens": 100, "output_tokens": 50}

    @property
    def model(self) -> str:
        return "fake-model"


# 실제 시장 데이터(tests/../data/input/sample_market_data.json)에 있는
# 숫자만 사용해서, wordpress_writer의 환각 방지 검사를 통과하도록 만든
# 정상적인 WordPressArticle 응답 샘플.
CANNED_WORDPRESS_ARTICLE = {
    "title": "미국 증시와 금리 전망 브리핑",
    "slug": "us-market-rate-outlook-briefing",
    "excerpt": "오늘 발표된 지수와 이벤트를 바탕으로 시장 흐름을 정리한다.",
    "meta_description": "오늘 발표된 지수와 이벤트를 바탕으로 시장 흐름을 정리한 분석글이다.",
    "content_markdown": (
        "## 핵심 답변\n"
        "주요 지수는 혼조세를 보였고 다음 이벤트가 변동성의 분수령이 될 전망이다.\n\n"
        "## 무슨 일이 일어났나\n"
        "주요 지수와 환율이 발표된 데이터에 따라 움직였다.\n\n"
        "## 왜 중요한가\n"
        "해당 지표는 향후 통화정책 경로에 영향을 줄 수 있다.\n\n"
        "## Bull case\n"
        "- 인플레이션 둔화가 이어질 경우 위험자산에 우호적일 수 있다.\n\n"
        "## Bear case\n"
        "- 예상보다 강한 고용지표가 나올 경우 되돌림이 발생할 수 있다.\n\n"
        "## 핵심 요약\n"
        "시장은 다음 이벤트를 주시하고 있다."
    ),
    "primary_keyword": "미국 증시",
    "related_keywords": ["금리", "인플레이션"],
}


@pytest.fixture
def fake_llm_client() -> FakeLlmClient:
    """정상적인 WordPressArticle JSON을 돌려주는 가짜 LlmClient."""
    return FakeLlmClient(json.dumps(CANNED_WORDPRESS_ARTICLE, ensure_ascii=False))
