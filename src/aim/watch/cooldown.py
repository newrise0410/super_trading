"""쿨다운 — 같은 (종목, 시그널 종류)의 반복 알림 억제.

prism-insight tools/reentry_cooldown.py 개념 (자체 구현). DB(signals 테이블) 기반이라
프로세스 재시작에도 유지된다.
"""

from __future__ import annotations

from datetime import datetime

from aim.storage.repositories.watch import SignalsRepository

FMT = "%Y-%m-%d %H:%M:%S"


class Cooldown:
    def __init__(self, signals_repo: SignalsRepository, minutes: int = 30) -> None:
        self._repo = signals_repo
        self._minutes = minutes

    def allow(self, symbol: str, kind: str, now: datetime) -> bool:
        last = self._repo.last_fired(symbol, kind)
        if last is None:
            return True
        elapsed = (now - datetime.strptime(last, FMT)).total_seconds() / 60
        return elapsed >= self._minutes
