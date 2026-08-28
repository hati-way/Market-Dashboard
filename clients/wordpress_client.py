"""WordPress REST API 클라이언트.

두 가지 인증 방식을 지원하며, `WORDPRESS_AUTH_MODE`(config.settings)로
선택한다.

- "app_password"(기본): self-hosted WordPress의 Application Password
  인증(HTTP Basic Auth)으로 `{WORDPRESS_URL}/wp-json/wp/v2/*` 를 호출한다.
- "wordpress_com_oauth2": WordPress.com Free 플랜처럼 Application
  Password를 지원하지 않는 사이트를 위한 OAuth2 access token(Bearer
  인증)으로 WordPress.com의 공식 프록시 엔드포인트
  `https://public-api.wordpress.com/wp/v2/sites/{site_id}/*` 를 호출한다.
  Access token 발급(OAuth2 authorize/token 교환) 자체는 이 클라이언트의
  책임이 아니다 — 이미 발급받은 access token을 .env에 넣어서 쓴다.

두 방식 모두 `posts`/`users/me` 같은 하위 경로와 요청/응답 형태가
동일하므로(WordPress.com이 wp/v2 API를 그대로 프록시한다), 이 클래스
하나가 base URL 구성과 인증 방식만 모드에 따라 바꿔서 나머지 로직
(create_post/update_post/get_post/find_post_by_slug/재시도/에러 분류)을
공유한다.

URL/계정/토큰은 항상 config.settings.get_settings() 를 통해서만 읽으며,
로그나 예외 메시지 어디에도 인증정보(Authorization 헤더, 비밀번호,
access token)를 직접 출력하지 않는다(요청 인증은 requests의 `auth=`
파라미터 또는 Authorization 헤더에만 실어 보내고, 로그는 상태 코드/시도
횟수 같은 메타 정보만 남긴다).
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

AUTH_MODE_APP_PASSWORD = "app_password"
AUTH_MODE_WORDPRESS_COM_OAUTH2 = "wordpress_com_oauth2"
_WORDPRESS_COM_API_ROOT = "https://public-api.wordpress.com"


class WordPressClientError(Exception):
    """WordPress 클라이언트 관련 오류의 공통 베이스."""


class WordPressConfigError(WordPressClientError):
    """인증 방식별 필수 설정이 없을 때 발생한다.

    (app_password: WORDPRESS_URL/USERNAME/APP_PASSWORD,
     wordpress_com_oauth2: WORDPRESS_COM_SITE_ID/ACCESS_TOKEN)
    """


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
        self._auth_mode = settings.wordpress_auth_mode
        # requests의 auth 파라미터(Basic) 또는 Authorization 헤더(Bearer)로만
        # 전달한다 — 둘 다 값 자체를 로그/예외 메시지에 넣지 않는다.
        self._auth: tuple[str, str] | None = None
        self._bearer_token: str | None = None

        if self._auth_mode == AUTH_MODE_WORDPRESS_COM_OAUTH2:
            if not settings.wordpress_com_site_id:
                raise WordPressConfigError(
                    "WORDPRESS_COM_SITE_ID가 설정되지 않았습니다. .env 파일에 값을 채워주세요."
                )
            if not settings.wordpress_com_access_token:
                raise WordPressConfigError(
                    "WORDPRESS_COM_ACCESS_TOKEN이 설정되지 않았습니다. "
                    ".env 파일에 값을 채워주세요."
                )
            site_id = settings.wordpress_com_site_id.strip().strip("/")
            self._base_url = f"{_WORDPRESS_COM_API_ROOT}/wp/v2/sites/{site_id}"
            self._bearer_token = settings.wordpress_com_access_token
        else:
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
            self._auth = (settings.wordpress_username, settings.wordpress_app_password)

        self._max_retries = max_retries if max_retries is not None else settings.wordpress_max_retries
        self._timeout = timeout if timeout is not None else settings.wordpress_timeout_seconds

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        if self._auth_mode == AUTH_MODE_WORDPRESS_COM_OAUTH2:
            # self._base_url 에 이미 /wp/v2/sites/{site_id} 까지 포함되어 있다.
            return f"{self._base_url}/{path}"
        return f"{self._base_url}/wp-json/wp/v2/{path}"

    def _request(self, method: str, path: str, **kwargs: object) -> dict | list:
        url = self._url(path)
        kwargs.setdefault("timeout", self._timeout)
        if self._bearer_token:
            headers = dict(kwargs.get("headers") or {})
            headers["Authorization"] = f"Bearer {self._bearer_token}"
            kwargs["headers"] = headers
        else:
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
