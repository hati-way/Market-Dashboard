"""LLM(OpenAI / Anthropic) 클라이언트 (아직 미구현).

OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 둘 중 설정된 것을 사용하도록
설계한다. 두 공급자를 같은 인터페이스(generate_text)로 감싸서, 상위
모듈(wordpress_writer 등)이 어떤 LLM을 쓰는지 신경 쓰지 않게 한다.
"""
from __future__ import annotations

from config.settings import get_settings


class LlmClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.openai_api_key = settings.openai_api_key
        self.anthropic_api_key = settings.anthropic_api_key

        if not self.openai_api_key and not self.anthropic_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 중 하나는 .env 에 설정되어야 합니다."
            )

    def generate_text(self, prompt: str, system_prompt: str | None = None) -> str:
        raise NotImplementedError("LLM 연동은 다음 단계에서 구현합니다.")
