"""Google Search Console API 클라이언트 (아직 미구현).

GOOGLE_SEARCH_CONSOLE_CREDENTIALS_PATH / GOOGLE_SEARCH_CONSOLE_SITE_URL
을 config.settings.get_settings() 로 읽어서 google-api-python-client 로
searchanalytics.query 를 호출하도록 구현할 예정이다.
"""
from __future__ import annotations

from config.settings import get_settings


class SearchConsoleClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.credentials_path = settings.google_search_console_credentials_path
        self.site_url = settings.google_search_console_site_url

    def fetch_page_metrics(self, page_url: str) -> dict:
        raise NotImplementedError("Search Console 연동은 다음 단계에서 구현합니다.")
