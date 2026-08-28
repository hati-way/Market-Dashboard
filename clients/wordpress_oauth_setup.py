"""WordPress.com OAuth2 Authorization Code Flow 로컬 setup helper.

`python main.py --wordpress-oauth-setup` 전용. 사용자가 curl을 직접
만들 필요 없이 access token을 발급받아 .env에 저장한다.

흐름:
    1. .env에 WORDPRESS_COM_CLIENT_ID/CLIENT_SECRET/REDIRECT_URI/SITE_ID
       가 모두 설정되어 있는지 확인한다. 값이 아니라 "어떤 키가
       없는지"만 알려준다.
    2. WordPress.com 공식 authorization URL을 만들어 기본 브라우저로
       열어본다(실패하면 URL만 출력한다).
    3. 사용자가 승인(Approve) 후 리다이렉트된 URL 전체 또는 code 값
       자체를 터미널에 붙여넣으면, 거기서 code만 추출한다.
    4. WordPress.com token endpoint를 호출해 access token을 발급받는다.
    5. .env 파일을 먼저 백업한 뒤, WORDPRESS_COM_ACCESS_TOKEN 줄만
       갱신한다(다른 줄의 내용/순서는 그대로 둔다). access token 값
       자체는 화면에 출력하지 않는다.

client_secret/authorization code/access_token은 어떤 로그나 예외
메시지에도 남기지 않는다. 이 모듈은 로컬 대화형 실행 전용이며,
파이프라인(pipeline/orchestrator.py)이나 WordPressClient 는 이 모듈을
전혀 참조하지 않는다.
"""
from __future__ import annotations

import logging
import re
import shutil
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)

AUTHORIZATION_ENDPOINT = "https://public-api.wordpress.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://public-api.wordpress.com/oauth2/token"
DEFAULT_ENV_PATH = Path(".env")
DEFAULT_TIMEOUT_SECONDS = 30.0

# .env에서 확인할 키 이름들. 값은 절대 로그/출력에 남기지 않고 이 키
# "이름"만 다룬다.
REQUIRED_ENV_KEYS = (
    "WORDPRESS_COM_CLIENT_ID",
    "WORDPRESS_COM_CLIENT_SECRET",
    "WORDPRESS_COM_REDIRECT_URI",
    "WORDPRESS_COM_SITE_ID",
)

_CODE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]+$")


class OAuthSetupError(Exception):
    """OAuth setup 진행 중 발생하는 오류의 공통 베이스."""


def find_missing_env_keys(env_values: dict[str, str | None]) -> list[str]:
    """REQUIRED_ENV_KEYS 중 값이 비어 있는 키 "이름"만 돌려준다 (값은 절대 포함하지 않는다)."""
    return [key for key in REQUIRED_ENV_KEYS if not env_values.get(key)]


def build_authorization_url(*, client_id: str, redirect_uri: str, site_id: str) -> str:
    """WordPress.com 공식 OAuth2 authorization URL을 만든다."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "blog": site_id,
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def extract_code_from_input(user_input: str) -> str | None:
    """리다이렉트된 URL 전체 또는 code 값 자체에서 authorization code를 추출한다.

    "https://.../callback?code=abc&state=..." 처럼 URL을 통째로
    붙여넣어도, "abc" 처럼 code만 붙여넣어도 둘 다 동작한다. 추출에
    실패하면 None을 돌려준다.
    """
    text = user_input.strip().strip('"').strip("'")
    if not text:
        return None

    if "?" in text:
        query = text.split("?", 1)[1]
        codes = parse_qs(query).get("code")
        return codes[0] if codes else None

    if _CODE_TOKEN_RE.fullmatch(text):
        return text

    return None


def exchange_code_for_token(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """WordPress.com token endpoint를 호출해 access token을 발급받는다.

    client_secret/code는 요청 본문에만 실어 보내고, 어떤 로그나 예외
    메시지에도 값 자체를 남기지 않는다.
    """
    try:
        response = requests.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("WordPress.com token 엔드포인트 호출 실패")
        raise OAuthSetupError("WordPress.com token 엔드포인트 호출에 실패했습니다.") from exc

    if response.status_code != 200:
        logger.warning("WordPress.com token 발급 거부 (상태 코드: %s)", response.status_code)
        raise OAuthSetupError(
            f"WordPress.com token 발급 요청이 거부되었습니다 (상태 코드: {response.status_code})."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise OAuthSetupError("WordPress.com token 응답을 JSON으로 파싱하지 못했습니다.") from exc

    if not isinstance(data, dict) or "access_token" not in data:
        raise OAuthSetupError("WordPress.com 응답에 access_token이 없습니다.")

    return data


def backup_env_file(env_path: Path) -> Path:
    """env_path 를 타임스탬프가 붙은 별도 파일로 복사해 둔다(내용 변경 없음)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = env_path.with_name(f"{env_path.name}.bak.{timestamp}")
    shutil.copy2(env_path, backup_path)
    return backup_path


def update_env_file(env_path: Path, key: str, value: str) -> None:
    """env_path 파일에서 `key=`로 시작하는 줄만 새 값으로 바꾼다.

    그런 줄이 없으면 파일 끝에 추가한다. 다른 줄의 내용/순서/주석은
    그대로 보존한다.
    """
    text = env_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    pattern = re.compile(rf"^{re.escape(key)}=")

    updated = False
    new_lines: list[str] = []
    for line in lines:
        body = line[:-1] if line.endswith("\n") else line
        if pattern.match(body):
            newline = "\n" if line.endswith("\n") else ""
            new_lines.append(f"{key}={value}{newline}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")

    env_path.write_text("".join(new_lines), encoding="utf-8")


def run_oauth_setup(
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    input_func: Callable[[str], str] = input,
    open_browser_func: Callable[[str], bool] = webbrowser.open,
    print_func: Callable[[str], None] = print,
) -> bool:
    """`--wordpress-oauth-setup` 의 전체 흐름을 실행한다.

    성공적으로 access token을 .env에 반영했으면 True, 중간에 멈췄으면
    (설정 누락, code 추출 실패, token 발급 실패 등) False를 돌려준다.
    """
    settings = get_settings()
    env_values = {
        "WORDPRESS_COM_CLIENT_ID": settings.wordpress_com_client_id,
        "WORDPRESS_COM_CLIENT_SECRET": settings.wordpress_com_client_secret,
        "WORDPRESS_COM_REDIRECT_URI": settings.wordpress_com_redirect_uri,
        "WORDPRESS_COM_SITE_ID": settings.wordpress_com_site_id,
    }

    missing = find_missing_env_keys(env_values)
    if missing:
        print_func("다음 환경변수가 .env에 설정되어 있지 않습니다:")
        for key in missing:
            print_func(f"  - {key}")
        print_func(".env 파일에 값을 채운 뒤 다시 실행하세요.")
        return False

    auth_url = build_authorization_url(
        client_id=env_values["WORDPRESS_COM_CLIENT_ID"],
        redirect_uri=env_values["WORDPRESS_COM_REDIRECT_URI"],
        site_id=env_values["WORDPRESS_COM_SITE_ID"],
    )

    print_func("아래 URL에서 WordPress.com에 로그인한 뒤 앱 접근을 승인(Approve)하세요:")
    print_func(auth_url)

    browser_opened = False
    try:
        browser_opened = bool(open_browser_func(auth_url))
    except Exception:
        browser_opened = False
    if browser_opened:
        print_func("(기본 브라우저에서 위 URL을 열었습니다. 열리지 않으면 직접 접속하세요.)")
    else:
        print_func("(브라우저를 자동으로 열지 못했습니다. 위 URL을 직접 여세요.)")

    print_func("")
    print_func(
        "승인 후 리다이렉트된 URL 전체(또는 code 값만)를 아래에 붙여넣고 Enter를 누르세요:"
    )
    user_input = input_func("> ")
    code = extract_code_from_input(user_input)
    if not code:
        print_func(
            "authorization code를 찾지 못했습니다. 리다이렉트된 URL 전체를 다시 붙여넣어 보세요."
        )
        return False

    try:
        token_data = exchange_code_for_token(
            client_id=env_values["WORDPRESS_COM_CLIENT_ID"],
            client_secret=env_values["WORDPRESS_COM_CLIENT_SECRET"],
            redirect_uri=env_values["WORDPRESS_COM_REDIRECT_URI"],
            code=code,
        )
    except OAuthSetupError as exc:
        print_func(f"access token 발급에 실패했습니다: {exc}")
        return False

    access_token = token_data["access_token"]

    backup_path = backup_env_file(env_path)
    update_env_file(env_path, "WORDPRESS_COM_ACCESS_TOKEN", access_token)

    print_func(f".env 백업을 만들었습니다: {backup_path}")
    print_func("WORDPRESS_COM_ACCESS_TOKEN 값을 .env에 저장했습니다 (값 자체는 출력하지 않습니다).")
    print_func("이제 다음 명령으로 연결을 확인하세요: python main.py --wordpress-test")
    return True
