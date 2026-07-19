"""콘솔 노티파이어 — 개발/드라이런용."""

from __future__ import annotations


class ConsoleNotifier:
    name = "console"

    def send(self, title: str, body_md: str) -> bool:
        print(f"\n{'=' * 60}\n[{self.name}] {title}\n{'=' * 60}")
        print(body_md)
        return True
