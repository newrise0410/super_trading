"""이벤트 버스 — 스케줄러는 이벤트만 발행하고, 파이프라인이 구독한다 (PLAN.md §10.6-5).

이벤트 이름 규약: "<market>_<session>" 예) market_open_kr, market_close_kr,
market_open_us, market_close_us, weekly_review
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

Handler = Callable[..., Any]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        self._handlers[event].append(handler)

    def publish(self, event: str, **payload: Any) -> list[Any]:
        """구독 핸들러를 순차 실행. 한 핸들러의 실패가 다른 핸들러를 막지 않는다."""
        results: list[Any] = []
        handlers = self._handlers.get(event, [])
        if not handlers:
            logger.warning("no handlers for event %s", event)
        for handler in handlers:
            try:
                results.append(handler(**payload))
            except Exception:  # noqa: BLE001 — 개별 핸들러 실패는 격리
                logger.exception("handler %s failed for event %s", handler, event)
                results.append(None)
        return results
