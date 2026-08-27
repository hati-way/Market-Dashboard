"""LLM 클라이언트.

앞으로 모든 콘텐츠 생성 모듈(wordpress_writer, threads_writer,
notebooklm_script, youtube_meta, thumbnail_prompt 등)은 특정 LLM SDK를
직접 import 하지 않고 이 클라이언트의 generate() 메서드만 사용한다.
다른 provider(OpenAI 등)를 추가할 때도 이 클래스와 동일한 인터페이스
(generate(user_prompt, system_prompt=None, ...) -> str)를 구현하면 된다.

지금은 Anthropic Claude API를 기본 provider로 구현한다. API 키는
반드시 config.settings.get_settings() 를 통해서만 읽으며, 코드/로그
어디에도 키 값을 직접 출력하지 않는다.

이번 단계에서는 클라이언트 자체까지만 구현한다. wordpress_writer 등의
placeholder 로직은 아직 이 클라이언트로 교체하지 않는다.
"""
from __future__ import annotations

import logging

import anthropic

from config.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2


class LlmClientError(Exception):
    """LLM 클라이언트 관련 오류의 공통 베이스."""


class LlmConfigError(LlmClientError):
    """API 키 등 필수 설정이 없을 때 발생한다."""


class LlmRetryableError(LlmClientError):
    """일시적인 오류로, 잠시 후 다시 시도하면 성공할 수 있는 경우.

    (timeout, 연결 오류, rate limit, 5xx 서버 오류 등)
    Anthropic SDK 자체도 내부적으로 재시도(max_retries)를 수행하므로,
    이 예외는 "SDK의 자체 재시도까지 모두 실패한 뒤"에만 발생한다.
    """


class LlmFatalError(LlmClientError):
    """다시 시도해도 성공할 수 없는 오류.

    (인증 실패, 잘못된 요청, 응답 형식 이상 등)
    """


class LlmClient:
    """Anthropic Claude 기반 LLM 클라이언트."""

    def __init__(self, max_retries: int = DEFAULT_MAX_RETRIES) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise LlmConfigError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                ".env 파일에 ANTHROPIC_API_KEY 값을 채워주세요."
            )

        self._model = settings.anthropic_model
        # anthropic.Anthropic 은 api_key를 내부에 보관할 뿐 로그로 노출하지 않는다.
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            max_retries=max_retries,
        )

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        """user_prompt(+ system_prompt)로 LLM 응답 텍스트를 생성한다.

        temperature 는 설치된 Anthropic SDK 버전의 메시지 API가 별도의
        typed 파라미터로 노출하지 않는 경우가 있어, extra_body 를 통해
        요청 본문에 직접 실어 보낸다.
        """
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": max_tokens,
            "timeout": timeout,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if temperature is not None:
            kwargs["extra_body"] = {"temperature": temperature}

        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            logger.error("Anthropic API 인증 실패 (상태 코드: %s)", exc.status_code)
            raise LlmFatalError(
                "Anthropic API 인증에 실패했습니다. ANTHROPIC_API_KEY 값을 확인하세요."
            ) from exc
        except anthropic.RateLimitError as exc:
            logger.warning("Anthropic API 호출 한도 초과 (상태 코드: %s)", exc.status_code)
            raise LlmRetryableError(
                "Anthropic API 호출 한도(rate limit)를 초과했습니다. 잠시 후 다시 시도하세요."
            ) from exc
        except anthropic.APITimeoutError as exc:
            logger.warning("Anthropic API 호출 시간 초과")
            raise LlmRetryableError("Anthropic API 호출이 시간 초과되었습니다.") from exc
        except anthropic.APIConnectionError as exc:
            logger.warning("Anthropic API 연결 실패")
            raise LlmRetryableError("Anthropic API 서버에 연결할 수 없습니다.") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                logger.warning("Anthropic API 서버 오류 (상태 코드: %s)", exc.status_code)
                raise LlmRetryableError(
                    f"Anthropic API 서버 오류가 발생했습니다 (상태 코드: {exc.status_code})."
                ) from exc
            logger.error("Anthropic API 요청 거부 (상태 코드: %s)", exc.status_code)
            raise LlmFatalError(
                f"Anthropic API 요청이 거부되었습니다 (상태 코드: {exc.status_code})."
            ) from exc
        except anthropic.APIError as exc:
            logger.error("Anthropic API 호출 중 알 수 없는 오류")
            raise LlmFatalError("Anthropic API 호출 중 알 수 없는 오류가 발생했습니다.") from exc

        return self._extract_text(response)

    @staticmethod
    def _extract_text(response: object) -> str:
        content = getattr(response, "content", None)
        if not content:
            raise LlmFatalError("Anthropic API 응답에 content가 없습니다.")

        text_blocks = [
            block.text for block in content if getattr(block, "type", None) == "text"
        ]
        if not text_blocks:
            raise LlmFatalError("Anthropic API 응답에 텍스트 콘텐츠가 없습니다.")

        return "\n".join(text_blocks)
