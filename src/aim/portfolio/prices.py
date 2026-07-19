"""포트폴리오 시세 조회 — 시장별 라우팅 (KR=KIS/pykrx, US=yfinance) + 환율."""

from __future__ import annotations

import logging
from typing import Callable

from aim.portfolio import PriceLookup

logger = logging.getLogger(__name__)

KRLookup = Callable[[str], tuple[float, float] | None]  # (symbol) -> (price, change%)


def us_last_price(symbol: str) -> tuple[float, float] | None:
    """yfinance — (최근가, 등락률%). 실패 시 None (격리)."""
    try:
        import yfinance as yf  # noqa: PLC0415

        info = yf.Ticker(symbol).fast_info
        price = float(info["last_price"])
        prev = float(info["previous_close"])
        change = (price / prev - 1) * 100 if prev else 0.0
        return price, round(change, 2)
    except Exception:  # noqa: BLE001
        logger.warning("US price lookup failed for %s", symbol)
        return None


def usdkrw() -> float | None:
    """USD/KRW 환율 (yfinance KRW=X). 실패 시 None → 통합 합계 생략."""
    try:
        import yfinance as yf  # noqa: PLC0415

        return float(yf.Ticker("KRW=X").fast_info["last_price"])
    except Exception:  # noqa: BLE001
        logger.warning("USDKRW lookup failed")
        return None


def make_lookup(kr_lookup: KRLookup, us_lookup=us_last_price) -> PriceLookup:
    """(symbol, market) 라우팅 룩업 생성."""

    def lookup(symbol: str, market: str) -> tuple[float, float] | None:
        try:
            return us_lookup(symbol) if market == "US" else kr_lookup(symbol)
        except Exception:  # noqa: BLE001 — 종목별 실패 격리
            logger.warning("price lookup failed for %s (%s)", symbol, market)
            return None

    return lookup
