"""clients/wordpress_client.py 테스트.

실제 WordPress 사이트는 절대 호출하지 않는다. requests.request 자체를
모킹해서 우리 코드의 재시도/오류 분류/URL 구성 로직만 검증한다.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from clients.wordpress_client import (
    WordPressClient,
    WordPressConfigError,
    WordPressFatalError,
    WordPressRetryableError,
)
from config.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_real_sleep():
    """재시도 백오프 때문에 테스트가 실제로 몇 초씩 기다리지 않게 한다."""
    with patch("clients.wordpress_client.time.sleep"):
        yield


def _set_wordpress_env(monkeypatch, url: str = "https://example.com") -> None:
    monkeypatch.setenv("WORDPRESS_URL", url)
    monkeypatch.setenv("WORDPRESS_USERNAME", "admin")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "sk-super-secret-app-password")


def _fake_response(status_code: int, json_body: object = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    return response


# ---- 설정 누락 ----


def test_missing_config_raises_config_error(monkeypatch):
    monkeypatch.delenv("WORDPRESS_URL", raising=False)
    with pytest.raises(WordPressConfigError):
        WordPressClient()


# ---- URL 정규화 (trailing slash 중복 방지) ----


def test_trailing_slash_is_normalized(monkeypatch):
    _set_wordpress_env(monkeypatch, url="https://example.com/")

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(200, {"id": 1})
        client = WordPressClient(max_retries=0)
        client.test_connection()

        args, _ = mock_request.call_args
        url = args[1]
        assert "//wp-json" not in url
        assert url == "https://example.com/wp-json/wp/v2/users/me"


# ---- 1. connection success ----


def test_connection_success(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(200, {"id": 1, "name": "Admin"})
        client = WordPressClient()
        result = client.test_connection()

        assert result == {"id": 1, "name": "Admin"}
        _, kwargs = mock_request.call_args
        assert kwargs["auth"] == ("admin", "sk-super-secret-app-password")


# ---- 2. authentication failure ----


def test_authentication_failure_raises_fatal(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(401, {"code": "rest_forbidden"})
        client = WordPressClient(max_retries=2)

        with pytest.raises(WordPressFatalError):
            client.test_connection()

        # 401은 재시도 대상이 아니므로 딱 한 번만 호출된다.
        assert mock_request.call_count == 1


# ---- 3. timeout ----


def test_timeout_raises_retryable_after_exhausting_retries(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.side_effect = requests.exceptions.Timeout()
        client = WordPressClient(max_retries=2)

        with pytest.raises(WordPressRetryableError):
            client.test_connection()

        assert mock_request.call_count == 3  # 최초 시도 + 재시도 2회 = 무한 재시도 아님


# ---- 4. 429 ----


def test_rate_limit_429_raises_retryable(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(429, {"code": "rate_limited"})
        client = WordPressClient(max_retries=1)

        with pytest.raises(WordPressRetryableError):
            client.test_connection()

        assert mock_request.call_count == 2


# ---- 5. 5xx는 재시도 후 성공하면 정상 반환 ----


def test_5xx_then_success_retries_and_returns_result(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.side_effect = [
            _fake_response(503, {"code": "unavailable"}),
            _fake_response(200, {"id": 1, "name": "Admin"}),
        ]
        client = WordPressClient(max_retries=2)
        result = client.test_connection()

        assert result == {"id": 1, "name": "Admin"}
        assert mock_request.call_count == 2


# ---- 6. 4xx(400)는 치명적 오류로 즉시 실패 ----


def test_bad_request_400_raises_fatal_without_retry(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(400, {"code": "invalid_param"})
        client = WordPressClient(max_retries=2)

        with pytest.raises(WordPressFatalError):
            client.create_post(title="t", content_html="<p>x</p>")

        assert mock_request.call_count == 1


# ---- 14. 인증정보가 로그/예외에 노출되지 않는지 ----


def test_credentials_never_appear_in_logs_or_exceptions(monkeypatch, caplog):
    secret_password = "sk-super-secret-app-password"
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(401, {"code": "rest_forbidden"})
        client = WordPressClient(max_retries=0)

        with caplog.at_level("DEBUG"):
            with pytest.raises(WordPressFatalError) as exc_info:
                client.test_connection()

    assert secret_password not in caplog.text
    assert secret_password not in str(exc_info.value)


# ---- create_post / find_post_by_slug 기본 동작 ----


def test_find_post_by_slug_returns_none_when_not_found(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(200, [])
        client = WordPressClient()

        assert client.find_post_by_slug("no-such-slug") is None


def test_find_post_by_slug_returns_first_match(monkeypatch):
    _set_wordpress_env(monkeypatch)

    with patch("clients.wordpress_client.requests.request") as mock_request:
        mock_request.return_value = _fake_response(200, [{"id": 7, "slug": "my-post"}])
        client = WordPressClient()

        result = client.find_post_by_slug("my-post")

        assert result == {"id": 7, "slug": "my-post"}
