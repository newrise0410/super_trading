"""알림 라우터 — 메시지 주제(route)를 채널별 Notifier로 배분.

route 체인: send(("surge", "signals"), ...) → 설정된 첫 번째 route의 채널로 발송,
전부 미설정이면 default로 폴백. 사용자는 원하는 만큼만 채널을 세분화하면 된다:
- #시그널 하나만 운영 → AIM_DISCORD_WEBHOOK_SIGNALS 하나 설정
- #급등주/#공시 분리 → _SURGE/_DISCLOSURE 추가 설정 (자동으로 세분 채널 우선)
"""

from __future__ import annotations

import logging
from typing import Sequence

from aim.config import Settings
from aim.delivery.notifier import Notifier

logger = logging.getLogger(__name__)


class NotificationRouter:
    def __init__(self, routes: dict[str, list[Notifier]], default: list[Notifier]) -> None:
        self._routes = routes
        self._default = default

    def send(self, route: str | Sequence[str], title: str, body_md: str) -> bool:
        chain = [route] if isinstance(route, str) else list(route)
        targets: list[Notifier] | None = None
        matched = "default"
        for r in chain:
            if self._routes.get(r):
                targets, matched = self._routes[r], r
                break
        if targets is None:
            targets = self._default

        ok = True
        for notifier in targets:
            sent = notifier.send(title, body_md)
            logger.info("route=%s via %s: %s", matched, notifier.name, "ok" if sent else "FAILED")
            ok = sent and ok
        return ok

    @property
    def configured_routes(self) -> list[str]:
        return sorted(self._routes)


def build_router(
    settings: Settings, *, respect_dry_run: bool = True, include_console: bool = True
) -> NotificationRouter:
    """설정 기반 라우터 — 디스코드 route별 채널 + default(기본 디스코드/텔레그램) + 콘솔."""
    from aim.delivery.console import ConsoleNotifier  # noqa: PLC0415

    console: list[Notifier] = [ConsoleNotifier()] if include_console else []
    allow_external = not (respect_dry_run and settings.dry_run)

    routes: dict[str, list[Notifier]] = {}
    default: list[Notifier] = list(console)

    if allow_external:
        from aim.delivery.discord import DiscordNotifier  # noqa: PLC0415

        for route, url in settings.discord_webhooks.items():
            if route == "default":
                default.append(DiscordNotifier(url))
            else:
                routes[route] = [*console, DiscordNotifier(url)]

        if settings.telegram_bot_token and settings.telegram_chat_id:
            from aim.delivery.telegram import TelegramNotifier  # noqa: PLC0415

            default.append(
                TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
            )

    if not default:
        default = [ConsoleNotifier()]
    return NotificationRouter(routes, default)
