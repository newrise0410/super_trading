"""Notifier 인터페이스 (§10.6-3) — 채널 추상화. FinceptTerminal의 17채널 프로바이더 개념 참고."""

from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    name: str

    def send(self, title: str, body_md: str) -> bool:
        """리포트/알람 발송. 성공 여부 반환 (실패 시 파이프라인이 로깅·재시도 판단)."""
        ...
