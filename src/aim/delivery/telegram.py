"""텔레그램 노티파이어 — Bot API 직접 호출(requests). 4096자 제한 분할 전송."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TELEGRAM_LIMIT = 4096


class TelegramNotifier:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        if not bot_token or not chat_id:
            raise ValueError("AIM_TELEGRAM_BOT_TOKEN / AIM_TELEGRAM_CHAT_ID 설정이 필요합니다 (.env)")
        self._token = bot_token
        self._chat_id = chat_id

    def send(self, title: str, body_md: str) -> bool:
        import requests  # noqa: PLC0415 — mock 경로 무의존 유지

        text = f"*{title}*\n\n{body_md}"
        ok = True
        for chunk in _split(text, _TELEGRAM_LIMIT):
            resp = requests.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=15,
            )
            if not resp.ok:
                # Markdown 파싱 실패 시 plain text로 1회 재시도
                resp = requests.post(
                    f"https://api.telegram.org/bot{self._token}/sendMessage",
                    json={"chat_id": self._chat_id, "text": chunk},
                    timeout=15,
                )
            if not resp.ok:
                logger.error("telegram send failed: %s %s", resp.status_code, resp.text[:200])
                ok = False
        return ok


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, current = [], []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and current:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks
