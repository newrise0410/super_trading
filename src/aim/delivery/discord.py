"""디스코드 노티파이어 — 웹훅 URL로 POST (봇 계정·게이트웨이 불필요).

- 2,000자 제한 → 줄 단위 분할 전송, 청크 간 0.5초 대기 (웹훅 레이트리밋 5req/2s 보호)
- ?wait=true 로 실제 게시 성공 확인 + 응답에서 스레드 ID 확보
- 채널 타입 자동 감지: 포럼 채널이면(thread_name 필수 → 400) 제목으로 새 포스트를
  만들고, 나머지 청크는 같은 스레드(thread_id)에 이어 붙인다.
  → 일반 채널·포럼 어느 쪽 웹훅이든 설정 없이 동작
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from aim.delivery.util import split_message

logger = logging.getLogger(__name__)

_DISCORD_LIMIT = 2000
_USERNAME = "AIM 투자매니저"

# 포럼 채널에 thread_name 없이 보냈을 때의 Discord 에러 코드
_FORUM_THREAD_REQUIRED = 220001


@dataclass(frozen=True)
class PostResult:
    status: int
    error_code: int | None = None   # Discord API error code (400대일 때)
    thread_id: str | None = None    # 게시된 스레드/채널 ID (wait=true 응답의 channel_id)


PostFn = Callable[[str, dict[str, Any], dict[str, str]], PostResult]
# (url, json_payload, query_params) -> PostResult


def _default_post(url: str, payload: dict[str, Any], params: dict[str, str]) -> PostResult:
    import requests  # noqa: PLC0415 — mock 경로 무의존 유지

    query = {"wait": "true", **params}

    def do() -> "requests.Response":
        return requests.post(url, json=payload, params=query, timeout=15)

    resp = do()
    if resp.status_code == 429:  # rate limited — 안내된 시간만큼 대기 후 1회 재시도
        retry_after = float(resp.json().get("retry_after", 1.0))
        logger.warning("discord rate limited — retrying after %.1fs", retry_after)
        time.sleep(retry_after)
        resp = do()

    error_code = None
    thread_id = None
    try:
        data = resp.json()
        if resp.status_code >= 400:
            error_code = data.get("code")
        else:
            thread_id = data.get("channel_id")
    except ValueError:
        pass
    return PostResult(resp.status_code, error_code, thread_id)


class DiscordNotifier:
    name = "discord"

    def __init__(self, webhook_url: str, *, post_fn: PostFn | None = None) -> None:
        if not webhook_url:
            raise ValueError("AIM_DISCORD_WEBHOOK_* 설정이 필요합니다 (.env)")
        self._url = webhook_url
        self._post = post_fn or _default_post
        self._is_forum: bool | None = None  # 첫 발송에서 감지 후 캐시

    def send(self, title: str, body_md: str) -> bool:
        chunks = split_message(body_md, _DISCORD_LIMIT)
        ok = True
        thread_id: str | None = None

        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"content": chunk, "username": _USERNAME}
            params: dict[str, str] = {}

            if thread_id:
                params["thread_id"] = thread_id          # 포럼: 같은 포스트에 이어 붙임
            elif self._is_forum:
                payload["thread_name"] = title           # 포럼: 제목으로 새 포스트
            elif i == 0:
                payload["content"] = f"## {title}\n\n{chunk}"  # 일반 채널: 제목을 본문에

            result = self._post(self._url, payload, params)

            # 포럼 채널 자동 감지: thread_name 필요 에러 → 포럼 모드로 1회 재시도
            if (
                result.status == 400
                and result.error_code == _FORUM_THREAD_REQUIRED
                and self._is_forum is None
            ):
                logger.info("discord: forum channel detected — retrying with thread_name")
                self._is_forum = True
                payload = {"content": chunk, "username": _USERNAME, "thread_name": title}
                result = self._post(self._url, payload, {})

            if self._is_forum is None:
                self._is_forum = False

            if result.status >= 400:
                logger.error(
                    "discord send failed: HTTP %s code=%s (chunk %d/%d)",
                    result.status, result.error_code, i + 1, len(chunks),
                )
                ok = False
            elif self._is_forum and thread_id is None:
                thread_id = result.thread_id             # 새 포스트의 스레드 ID 확보

            if i < len(chunks) - 1:
                time.sleep(0.5)  # 레이트리밋 보호
        return ok
