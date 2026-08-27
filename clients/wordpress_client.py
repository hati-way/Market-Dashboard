"""WordPress REST API 클라이언트 (아직 미구현).

향후 구현 시 config.settings.get_settings() 로 WORDPRESS_URL /
WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD 를 읽어서
`requests` 로 `/wp-json/wp/v2/posts` 등을 호출하면 된다.

절대 URL/계정/비밀번호를 코드에 직접 쓰지 말고 항상
config.settings.get_settings() 를 통해서만 읽을 것.
"""
from __future__ import annotations

from config.settings import get_settings


class WordPressClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.wordpress_url
        self.username = settings.wordpress_username
        self.app_password = settings.wordpress_app_password

    def create_post(self, title: str, content_html: str, status: str = "draft") -> dict:
        raise NotImplementedError("WordPress REST API 연동은 다음 단계에서 구현합니다.")
