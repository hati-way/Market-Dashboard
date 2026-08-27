"""WordPress REST API 클라이언트.

WordPress Application Password 인증(HTTP Basic Auth)으로
`/wp-json/wp/v2/*` 엔드포인트를 호출한다. URL/계정/비밀번호는 항상
config.settings.get_settings() 를 통해서만 읽으며, 로그나 예외 메시지
어디에도 인증정보(Authorization 헤더, 비밀번호)를 직접 출력하지 않는다
(요청 인증은 requests의 `auth=` 파라미터에만 맡기고, 로그는 상태
코드/시도 횟수 같은 메타 정보만 남긴다).
"""
from __future__ import annotations

import logging
import time

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 1.0


class WordPressClientError(Exception):
    """WordPress 클라이언트 관련 오류의 공통 베이스."""


class WordPressConfigError(WordPressClientError):
    """WORDPRESS_URL/USERNAME/APP_PASSWORD 등 필수 설정이 없을 때 발생한다."""


class WordPressRetryableError(WordPressClientError):
    """일시적인 오류로, 잠시 후 다시 시도하면 성공할 수 있는 경우.

    (timeout, 연결 오류, 429, 5xx)
    """


class WordPressFatalError(WordPressClientError):
    """다시 시도해도 성공할 수 없는 오류. (400/401/403/404 등)"""


class WordPressClient:
    """WordPress REST API(`wp/v2`) 클라이언트."""

    def __init__(
        self,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.wordpress_url:
            raise WordPressConfigError(
                "WORDPRESS_URL이 설정되지 않았습니다. .env 파일에 값을 채워주세요."
            )
        if not settings.wordpress_username or not settings.wordpress_app_password:
            raise WordPressConfigError(
                "WORDPRESS_USERNAME/WORDPRESS_APP_PASSWORD가 설정되지 않았습니다. "
                ".env 파일에 값을 채워주세요."
            )

        # 끝의 슬래시를 제거해 /wp-json 이 중복되지 않게 한다.
        self._base_url = settings.wordpress_url.rstrip("/")
        # requests의 auth 파라미터로만 전달한다 — Authorization 헤더나
        # 비밀번호 값 자체를 로그/예외 메시지에 넣지 않는다.
        self._auth = (settings.wordpress_username, settings.wordpress_app_password)
        self._max_retries = max_retries if max_retries is not None else settings.wordpress_max_retries
        self._timeout = timeout if timeout is not None else settings.wordpress_timeout_seconds

    def _url(self, path: str) -> str:
        return f"{self._base_url}/wp-json/wp/v2/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: object) -> dict | list:
        url = self._url(path)
        kwargs.setdefault("timeout", self._timeout)
        kwargs["auth"] = self._auth

        last_exc: Exception | None = None
        total_attempts = self._max_retries + 1

        for attempt in range(total_attempts):
            try:
                response = requests.request(method, url, **kwargs)
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                logger.warning(
                    "WordPress API 호출 시간 초과 (시도 %s/%s): %s %s",
                    attempt + 1, total_attempts, method, path,
                )
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                logger.warning(
                    "WordPress API 연결 실패 (시도 %s/%s): %s %s",
                    attempt + 1, total_attempts, method, path,
                )
            else:
                status = response.status_code
                if status == 429 or status >= 500:
                    last_exc = WordPressRetryableError(
                        f"WordPress API 응답 오류 (상태 코드: {status})"
                    )
                    logger.warning(
                        "WordPress API 재시도 가능한 오류 (상태 코드: %s, 시도 %s/%s)",
                        status, attempt + 1, total_attempts,
                    )
                elif 400 <= status < 500:
                    logger.error("WordPress API 요청 거부 (상태 코드: %s)", status)
                    raise WordPressFatalError(
                        f"WordPress API 요청이 거부되었습니다 (상태 코드: {status})."
                    )
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise WordPressFatalError(
                            "WordPress API 응답을 JSON으로 파싱하지 못했습니다."
                        ) from exc

            if attempt < total_attempts - 1:
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise WordPressRetryableError(
            f"WordPress API 호출이 재시도 {self._max_retries}회 후에도 실패했습니다."
        ) from last_exc

    def test_connection(self) -> dict:
        """인증정보가 유효하고 사이트에 접근 가능한지 확인한다."""
        result = self._request("GET", "users/me")
        return result if isinstance(result, dict) else {}

    def create_post(
        self,
        *,
        title: str,
        content_html: str,
        excerpt: str = "",
        slug: str = "",
        status: str = "draft",
    ) -> dict:
        payload: dict[str, object] = {"title": title, "content": content_html, "status": status}
        if excerpt:
            payload["excerpt"] = excerpt
        if slug:
            payload["slug"] = slug
        result = self._request("POST", "posts", json=payload)
        return result if isinstance(result, dict) else {}

    def update_post(
        self,
        post_id: int,
        *,
        title: str | None = None,
        content_html: str | None = None,
        excerpt: str | None = None,
        slug: str | None = None,
        status: str | None = None,
    ) -> dict:
        payload: dict[str, object] = {}
        if title is not None:
            payload["title"] = title
        if content_html is not None:
            payload["content"] = content_html
        if excerpt is not None:
            payload["excerpt"] = excerpt
        if slug is not None:
            payload["slug"] = slug
        if status is not None:
            payload["status"] = status
        result = self._request("POST", f"posts/{post_id}", json=payload)
        return result if isinstance(result, dict) else {}

    def get_post(self, post_id: int) -> dict:
        result = self._request("GET", f"posts/{post_id}")
        return result if isinstance(result, dict) else {}

    def find_post_by_slug(self, slug: str) -> dict | None:
        """slug가 일치하는 글을 찾는다 (draft 포함, 없으면 None)."""
        results = self._request(
            "GET", "posts", params={"slug": slug, "status": "any", "context": "edit"}
        )
        if isinstance(results, list) and results:
            return results[0]
        return None
