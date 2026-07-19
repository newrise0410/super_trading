"""MiniMax 백엔드 — OpenAI 호환 chat completions (퀵씽킹 티어).

- MiniMax-M2는 응답에 <think>...</think> 추론 블록을 섞을 수 있음 → 제거 후 반환
  (Vibe-Trading providers/capabilities.py에서 확인된 특성)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

PostFn = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]
# (url, headers, json_body) -> response json


def _default_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    import requests  # noqa: PLC0415

    resp = requests.post(url, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    return resp.json()


class MiniMaxClient:
    name = "minimax"

    def __init__(
        self,
        api_key: str,
        model: str = "MiniMax-M2",
        base_url: str = "https://api.minimax.io/v1",
        *,
        post_fn: PostFn | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("AIM_MINIMAX_API_KEY 설정이 필요합니다 (.env)")
        self._key = api_key
        self.model = model
        self._base = base_url.rstrip("/")
        self._post = post_fn or _default_post

    def complete(self, system: str, user: str) -> str:
        data = self._post(
            f"{self._base}/chat/completions",
            {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"MiniMax 빈 응답: {str(data)[:200]}")
        content = choices[0].get("message", {}).get("content", "")
        return _THINK_RE.sub("", content).strip()
