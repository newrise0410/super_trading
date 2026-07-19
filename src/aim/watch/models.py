from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IntradayQuote:
    """장중 시세 스냅샷 (KIS 현재가 폴링 1회분)."""
    symbol: str
    name: str
    price: float
    change_pct: float
    cum_volume: float      # 당일 누적 거래량 (주)
    cum_value: float       # 당일 누적 거래대금 (억원)
    at: str                # "YYYY-MM-DD HH:MM:SS" (KST)
    per: float | None = None   # 밸류에이션 (KIS 현재가 응답 포함 — 소크라 레슨 재료)
    pbr: float | None = None


@dataclass(frozen=True)
class Disclosure:
    """공시 1건 (DART 폴링)."""
    symbol: str
    corp_name: str
    title: str
    filed_at: str          # "YYYY-MM-DD HH:MM"
    url: str = ""
    category: str = ""     # signals.classify_disclosure()로 분류


@dataclass(frozen=True)
class Signal:
    kind: str              # VOLUME_SURGE | VALUE_SPIKE | PRICE_MOVE | DISCLOSURE | COMBO
    symbol: str
    name: str
    severity: str          # info | notable | critical
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
