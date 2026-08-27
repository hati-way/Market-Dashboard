"""clients/llm_client.py 테스트.

실제 Anthropic API는 절대 호출하지 않는다. anthropic.Anthropic 클라이언트
자체를 모킹하고, 필요한 경우 실제 anthropic 예외 클래스의 인스턴스를
(httpx2.Request/Response 로) 직접 만들어 우리 코드의 예외 분류 로직만
검증한다.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx2
import pytest

from config.settings import get_settings
from clients.llm_client import (
    LlmClient,
    LlmConfigError,
    LlmFatalError,
    LlmRetryableError,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fake_request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _fake_status_error(status_code: int, exc_cls=anthropic.APIStatusError):
    response = httpx2.Response(
        status_code, request=_fake_request(), json={"error": {"message": "boom"}}
    )
    return exc_cls("boom", response=response, body=None)


def _fake_text_response(text: str = "hello world"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


# ---- API key 미설정 ----


def test_missing_api_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LlmConfigError):
        LlmClient()


# ---- 정상 응답 ----


def test_generate_success(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _fake_text_response("안녕하세요")
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        result = client.generate("주제를 요약해줘", system_prompt="너는 금융 애널리스트다")

        assert result == "안녕하세요"

        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["model"] == "claude-sonnet-5"
        assert kwargs["system"] == "너는 금융 애널리스트다"
        assert kwargs["messages"] == [{"role": "user", "content": "주제를 요약해줘"}]

        # Claude Sonnet 5는 temperature/top_p/top_k 같은 비기본 sampling
        # 파라미터를 보내면 오류가 날 수 있으므로 기본 경로에서는 아예
        # 요청에 포함되지 않아야 한다.
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs
        assert "top_k" not in kwargs
        assert "extra_body" not in kwargs


def test_generate_passes_extra_options_via_extra_body(monkeypatch):
    """모델별로 다른 옵션(예: 향후 effort/thinking)을 위한 확장 지점 테스트.

    기본 경로에서는 아무도 채우지 않지만, 필요할 때 extra_options 로
    넘긴 값이 그대로 extra_body 로 전달되는지 확인한다.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _fake_text_response()
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        client.generate("hi", extra_options={"future_option": "value"})

        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["extra_body"] == {"future_option": "value"}
        assert "temperature" not in kwargs


# ---- 인증정보 없음(잘못된 키로 API가 거부) ----


def test_generate_authentication_error_raises_fatal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-invalid")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _fake_status_error(
            401, anthropic.AuthenticationError
        )
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmFatalError):
            client.generate("hi")


# ---- timeout ----


def test_generate_timeout_raises_retryable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APITimeoutError(
            request=_fake_request()
        )
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmRetryableError):
            client.generate("hi")


def test_generate_connection_error_raises_retryable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIConnectionError(
            request=_fake_request()
        )
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmRetryableError):
            client.generate("hi")


# ---- API 오류 (rate limit / 5xx = 재시도 가능, 4xx = 치명적) ----


def test_generate_rate_limit_raises_retryable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _fake_status_error(
            429, anthropic.RateLimitError
        )
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmRetryableError):
            client.generate("hi")


def test_generate_server_error_raises_retryable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _fake_status_error(529)
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmRetryableError):
            client.generate("hi")


def test_generate_bad_request_raises_fatal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _fake_status_error(
            400, anthropic.BadRequestError
        )
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmFatalError):
            client.generate("hi")


# ---- 잘못된 응답 ----


def test_generate_response_without_content_raises_fatal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(content=[])
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmFatalError):
            client.generate("hi")


def test_generate_response_without_text_block_raises_fatal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        # 텍스트가 아닌 블록(tool_use 등)만 있는 경우
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input={})]
        )
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with pytest.raises(LlmFatalError):
            client.generate("hi")


# ---- API 키가 로그에 출력되지 않는지 확인 ----


def test_api_key_never_logged(monkeypatch, caplog):
    secret_key = "sk-super-secret-value-should-not-leak"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret_key)

    with patch("clients.llm_client.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _fake_status_error(
            401, anthropic.AuthenticationError
        )
        mock_anthropic_cls.return_value = mock_client

        client = LlmClient()
        with caplog.at_level("DEBUG"):
            with pytest.raises(LlmFatalError):
                client.generate("hi")

    assert secret_key not in caplog.text
