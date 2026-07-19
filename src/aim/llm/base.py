from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str:
        """단발 완성 호출 — 최종 텍스트 반환. 실패 시 예외 (호출부가 격리 판단)."""
        ...
