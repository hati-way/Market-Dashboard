"""환경변수(.env) 로드 및 전역 설정.

모든 API 키와 비밀값은 여기를 통해서만 읽는다. 코드 어디에도 키를 직접
하드코딩하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()  # 프로젝트 루트의 .env 파일을 읽어 os.environ 에 채워 넣는다.


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str

    wordpress_url: str | None
    wordpress_username: str | None
    wordpress_app_password: str | None

    openai_api_key: str | None
    anthropic_api_key: str | None
    anthropic_model: str

    google_search_console_credentials_path: str | None
    google_search_console_site_url: str | None

    threads_access_token: str | None


@lru_cache
def get_settings() -> Settings:
    """환경변수를 읽어 Settings 객체를 반환한다 (프로세스당 1회만 로드)."""
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        wordpress_url=os.getenv("WORDPRESS_URL") or None,
        wordpress_username=os.getenv("WORDPRESS_USERNAME") or None,
        wordpress_app_password=os.getenv("WORDPRESS_APP_PASSWORD") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5",
        google_search_console_credentials_path=os.getenv(
            "GOOGLE_SEARCH_CONSOLE_CREDENTIALS_PATH"
        )
        or None,
        google_search_console_site_url=os.getenv("GOOGLE_SEARCH_CONSOLE_SITE_URL")
        or None,
        threads_access_token=os.getenv("THREADS_ACCESS_TOKEN") or None,
    )
