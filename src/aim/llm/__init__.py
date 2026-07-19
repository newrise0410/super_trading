"""LLM 레이어 — 2-티어 (TradingAgents 비용 최적화 패턴, PLAN.md §3).

- deep(딥씽킹): 판정자 역할 — Codex CLI(ChatGPT 구독 OAuth). 호출당 느리지만 강력
- quick(퀵씽킹): 애널리스트 역할 — MiniMax API. 싸고 빠름

build_llm(settings, tier)로 획득. 한쪽이 미설정이면 다른 쪽으로 폴백 —
프로바이더 교체는 이 팩토리만 수정하면 된다.
"""

from __future__ import annotations

from aim.config import Settings
from aim.llm.base import LLMClient


def build_llm(settings: Settings, tier: str = "quick") -> LLMClient:
    """tier: "deep" | "quick". 미설정 티어는 반대쪽으로 폴백."""
    from aim.llm.codex_cli import CodexCLIClient, codex_available  # noqa: PLC0415
    from aim.llm.minimax import MiniMaxClient  # noqa: PLC0415

    has_codex = codex_available()
    has_minimax = bool(settings.minimax_api_key)

    if tier == "deep":
        if has_codex:
            return CodexCLIClient(model=settings.codex_model)
        if has_minimax:
            return MiniMaxClient(
                settings.minimax_api_key, settings.minimax_model, settings.minimax_base_url
            )
    else:  # quick
        if has_minimax:
            return MiniMaxClient(
                settings.minimax_api_key, settings.minimax_model, settings.minimax_base_url
            )
        if has_codex:
            return CodexCLIClient(model=settings.codex_model)

    raise RuntimeError(
        "사용 가능한 LLM이 없습니다 — `codex login` 또는 .env의 AIM_MINIMAX_API_KEY를 설정하세요"
    )


__all__ = ["build_llm", "LLMClient"]
