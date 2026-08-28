"""clients/wordpress_oauth_setup.py 테스트.

실제 WordPress.com 사이트/OAuth2 엔드포인트는 절대 호출하지 않는다
(requests.post를 모킹한다). 이 테스트는 절대 진짜 프로젝트의 .env
파일을 건드리지 않고, pytest의 tmp_path 에 만든 임시 .env 파일만
사용한다.
"""
import re
from unittest.mock import MagicMock, patch

import pytest
import requests

from clients.wordpress_oauth_setup import (
    REQUIRED_ENV_KEYS,
    OAuthSetupError,
    backup_env_file,
    build_authorization_url,
    exchange_code_for_token,
    extract_code_from_input,
    find_missing_env_keys,
    run_oauth_setup,
    update_env_file,
)
from config.settings import get_settings

SECRET_CLIENT_SECRET = "wpcom-super-secret-client-secret"
SECRET_CODE = "abc123authcode"
SECRET_ACCESS_TOKEN = "wpcom-super-secret-access-token-xyz"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_oauth_env(monkeypatch, **overrides) -> None:
    values = {
        "WORDPRESS_COM_CLIENT_ID": "client-id-123",
        "WORDPRESS_COM_CLIENT_SECRET": SECRET_CLIENT_SECRET,
        "WORDPRESS_COM_REDIRECT_URI": "https://example.com/callback",
        "WORDPRESS_COM_SITE_ID": "example.wordpress.com",
    }
    values.update(overrides)
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def _fake_response(status_code: int, json_body: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


# ---- find_missing_env_keys ----


def test_find_missing_env_keys_reports_only_missing_names():
    env_values = {
        "WORDPRESS_COM_CLIENT_ID": "id",
        "WORDPRESS_COM_CLIENT_SECRET": "",
        "WORDPRESS_COM_REDIRECT_URI": None,
        "WORDPRESS_COM_SITE_ID": "example.wordpress.com",
    }

    missing = find_missing_env_keys(env_values)

    assert missing == ["WORDPRESS_COM_CLIENT_SECRET", "WORDPRESS_COM_REDIRECT_URI"]


def test_required_env_keys_matches_expected_set():
    assert set(REQUIRED_ENV_KEYS) == {
        "WORDPRESS_COM_CLIENT_ID",
        "WORDPRESS_COM_CLIENT_SECRET",
        "WORDPRESS_COM_REDIRECT_URI",
        "WORDPRESS_COM_SITE_ID",
    }


# ---- build_authorization_url ----


def test_build_authorization_url_contains_expected_params():
    url = build_authorization_url(
        client_id="client-id-123",
        redirect_uri="https://example.com/callback",
        site_id="example.wordpress.com",
    )

    assert url.startswith("https://public-api.wordpress.com/oauth2/authorize?")
    assert "client_id=client-id-123" in url
    assert "response_type=code" in url
    assert "blog=example.wordpress.com" in url
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url


# ---- extract_code_from_input ----


def test_extract_code_from_full_redirect_url():
    user_input = "https://example.com/callback?code=abc123authcode&state=xyz"
    assert extract_code_from_input(user_input) == "abc123authcode"


def test_extract_code_from_bare_code():
    assert extract_code_from_input("abc123authcode") == "abc123authcode"


def test_extract_code_from_quoted_bare_code():
    assert extract_code_from_input('"abc123authcode"') == "abc123authcode"


def test_extract_code_returns_none_for_empty_input():
    assert extract_code_from_input("   ") is None


def test_extract_code_returns_none_when_url_has_no_code_param():
    assert extract_code_from_input("https://example.com/callback?state=xyz") is None


def test_extract_code_returns_none_for_garbage_input():
    assert extract_code_from_input("this is not a code or url!!") is None


# ---- exchange_code_for_token ----


def test_exchange_code_for_token_success():
    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.return_value = _fake_response(200, {"access_token": SECRET_ACCESS_TOKEN, "blog_id": 1})

        result = exchange_code_for_token(
            client_id="client-id-123",
            client_secret=SECRET_CLIENT_SECRET,
            redirect_uri="https://example.com/callback",
            code=SECRET_CODE,
        )

        assert result["access_token"] == SECRET_ACCESS_TOKEN
        _, kwargs = mock_post.call_args
        assert kwargs["data"]["client_secret"] == SECRET_CLIENT_SECRET
        assert kwargs["data"]["code"] == SECRET_CODE
        assert kwargs["data"]["grant_type"] == "authorization_code"


def test_exchange_code_for_token_rejected_raises_oauth_setup_error():
    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.return_value = _fake_response(400, {"error": "invalid_request"})

        with pytest.raises(OAuthSetupError):
            exchange_code_for_token(
                client_id="client-id-123",
                client_secret=SECRET_CLIENT_SECRET,
                redirect_uri="https://example.com/callback",
                code=SECRET_CODE,
            )


def test_exchange_code_for_token_network_error_raises_oauth_setup_error():
    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(OAuthSetupError):
            exchange_code_for_token(
                client_id="client-id-123",
                client_secret=SECRET_CLIENT_SECRET,
                redirect_uri="https://example.com/callback",
                code=SECRET_CODE,
            )


def test_exchange_code_for_token_missing_access_token_raises_error():
    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.return_value = _fake_response(200, {"blog_id": 1})

        with pytest.raises(OAuthSetupError):
            exchange_code_for_token(
                client_id="client-id-123",
                client_secret=SECRET_CLIENT_SECRET,
                redirect_uri="https://example.com/callback",
                code=SECRET_CODE,
            )


def test_exchange_code_for_token_error_never_leaks_secret_in_logs(caplog):
    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.return_value = _fake_response(401, {"error": "invalid_client"})

        with caplog.at_level("DEBUG"):
            with pytest.raises(OAuthSetupError) as exc_info:
                exchange_code_for_token(
                    client_id="client-id-123",
                    client_secret=SECRET_CLIENT_SECRET,
                    redirect_uri="https://example.com/callback",
                    code=SECRET_CODE,
                )

    assert SECRET_CLIENT_SECRET not in caplog.text
    assert SECRET_CODE not in caplog.text
    assert SECRET_CLIENT_SECRET not in str(exc_info.value)
    assert SECRET_CODE not in str(exc_info.value)


# ---- update_env_file / backup_env_file ----


def test_update_env_file_replaces_existing_key_in_place(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "WORDPRESS_URL=https://example.com\n"
        "WORDPRESS_COM_ACCESS_TOKEN=old-value\n"
        "ANTHROPIC_API_KEY=sk-anthropic\n",
        encoding="utf-8",
    )

    update_env_file(env_path, "WORDPRESS_COM_ACCESS_TOKEN", SECRET_ACCESS_TOKEN)

    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "WORDPRESS_URL=https://example.com"
    assert lines[1] == f"WORDPRESS_COM_ACCESS_TOKEN={SECRET_ACCESS_TOKEN}"
    assert lines[2] == "ANTHROPIC_API_KEY=sk-anthropic"


def test_update_env_file_appends_key_when_missing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("WORDPRESS_URL=https://example.com\n", encoding="utf-8")

    update_env_file(env_path, "WORDPRESS_COM_ACCESS_TOKEN", SECRET_ACCESS_TOKEN)

    content = env_path.read_text(encoding="utf-8")
    assert "WORDPRESS_URL=https://example.com" in content
    assert f"WORDPRESS_COM_ACCESS_TOKEN={SECRET_ACCESS_TOKEN}" in content


def test_backup_env_file_creates_separate_timestamped_copy(tmp_path):
    env_path = tmp_path / ".env"
    original_content = "WORDPRESS_URL=https://example.com\nFOO=bar\n"
    env_path.write_text(original_content, encoding="utf-8")

    backup_path = backup_env_file(env_path)

    assert backup_path != env_path
    assert backup_path.exists()
    assert re.match(r"\.env\.bak\.\d{8}T\d{6}Z$", backup_path.name)
    assert backup_path.read_text(encoding="utf-8") == original_content
    # 원본은 그대로 남아 있어야 한다.
    assert env_path.read_text(encoding="utf-8") == original_content


# ---- run_oauth_setup (전체 흐름) ----


def test_run_oauth_setup_reports_missing_keys_without_leaking_values(monkeypatch):
    _set_oauth_env(monkeypatch, WORDPRESS_COM_CLIENT_SECRET=None)
    printed: list[str] = []

    result = run_oauth_setup(
        input_func=lambda _prompt: pytest.fail("input이 호출되면 안 된다"),
        open_browser_func=lambda _url: pytest.fail("browser가 열리면 안 된다"),
        print_func=printed.append,
    )

    assert result is False
    joined = "\n".join(printed)
    assert "WORDPRESS_COM_CLIENT_SECRET" in joined
    assert SECRET_CLIENT_SECRET not in joined


def test_run_oauth_setup_full_success_updates_env_and_hides_secrets(monkeypatch, tmp_path):
    _set_oauth_env(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "WORDPRESS_URL=https://example.com\nWORDPRESS_COM_ACCESS_TOKEN=\n",
        encoding="utf-8",
    )

    printed: list[str] = []
    browser_calls: list[str] = []

    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.return_value = _fake_response(200, {"access_token": SECRET_ACCESS_TOKEN})

        result = run_oauth_setup(
            env_path=env_path,
            input_func=lambda _prompt: f"https://example.com/callback?code={SECRET_CODE}",
            open_browser_func=lambda url: browser_calls.append(url) or True,
            print_func=printed.append,
        )

    assert result is True
    assert browser_calls  # authorization URL로 브라우저를 열려고 시도했다.

    updated_content = env_path.read_text(encoding="utf-8")
    assert f"WORDPRESS_COM_ACCESS_TOKEN={SECRET_ACCESS_TOKEN}" in updated_content
    assert "WORDPRESS_URL=https://example.com" in updated_content  # 다른 값은 보존

    # 백업 파일이 만들어졌고, 원래 내용을 담고 있어야 한다.
    backups = list(tmp_path.glob(".env.bak.*"))
    assert len(backups) == 1
    assert "WORDPRESS_COM_ACCESS_TOKEN=\n" in backups[0].read_text(encoding="utf-8")

    joined_output = "\n".join(printed)
    assert SECRET_ACCESS_TOKEN not in joined_output
    assert SECRET_CLIENT_SECRET not in joined_output
    assert SECRET_CODE not in joined_output


def test_run_oauth_setup_invalid_code_input_does_not_call_token_endpoint(monkeypatch, tmp_path):
    _set_oauth_env(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("WORDPRESS_COM_ACCESS_TOKEN=\n", encoding="utf-8")

    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        result = run_oauth_setup(
            env_path=env_path,
            input_func=lambda _prompt: "not a valid url or code !!",
            open_browser_func=lambda _url: True,
            print_func=lambda _msg: None,
        )

        mock_post.assert_not_called()

    assert result is False
    # 실패했으므로 .env는 갱신되지 않아야 한다.
    assert env_path.read_text(encoding="utf-8") == "WORDPRESS_COM_ACCESS_TOKEN=\n"


def test_run_oauth_setup_token_failure_does_not_touch_env_file(monkeypatch, tmp_path):
    _set_oauth_env(monkeypatch)
    env_path = tmp_path / ".env"
    original = "WORDPRESS_COM_ACCESS_TOKEN=\n"
    env_path.write_text(original, encoding="utf-8")

    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.return_value = _fake_response(400, {"error": "invalid_grant"})

        result = run_oauth_setup(
            env_path=env_path,
            input_func=lambda _prompt: f"https://example.com/callback?code={SECRET_CODE}",
            open_browser_func=lambda _url: True,
            print_func=lambda _msg: None,
        )

    assert result is False
    assert env_path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".env.bak.*"))


def test_run_oauth_setup_falls_back_to_url_only_when_browser_open_fails(monkeypatch, tmp_path):
    _set_oauth_env(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("WORDPRESS_COM_ACCESS_TOKEN=\n", encoding="utf-8")
    printed: list[str] = []

    def _raise_open(_url):
        raise RuntimeError("no display")

    with patch("clients.wordpress_oauth_setup.requests.post") as mock_post:
        mock_post.return_value = _fake_response(200, {"access_token": SECRET_ACCESS_TOKEN})

        result = run_oauth_setup(
            env_path=env_path,
            input_func=lambda _prompt: f"https://example.com/callback?code={SECRET_CODE}",
            open_browser_func=_raise_open,
            print_func=printed.append,
        )

    assert result is True
    joined = "\n".join(printed)
    assert "https://public-api.wordpress.com/oauth2/authorize" in joined
