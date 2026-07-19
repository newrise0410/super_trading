"""증거 수집기 v1 — pykrx 기반 (기술·수급 축). 파생지표는 전부 여기서 계산.

축 실패는 격리: 한 축이 실패해도 나머지로 진행, gaps에 기록.
확장 예정: DART 공시(event), 뉴스(news), KIS 재무(fundamental).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from aim.evidence.models import EvidenceItem, StockEvidence

logger = logging.getLogger(__name__)


def collect_kr_evidence(symbol: str, as_of: str | None = None) -> StockEvidence:
    """pykrx로 KR 종목의 기술·수급 증거 수집 (약 1년 일봉 + 최근 수급)."""
    from pykrx import stock  # noqa: PLC0415

    as_of = as_of or date.today().isoformat()
    end = as_of.replace("-", "")
    start = (date.fromisoformat(as_of) - timedelta(days=400)).strftime("%Y%m%d")

    name = stock.get_market_ticker_name(symbol) or symbol
    items: list[EvidenceItem] = []
    gaps: list[str] = []

    # ── 가격/기술 축 ─────────────────────────────────────────────
    price, change_pct = 0.0, 0.0
    try:
        df = stock.get_market_ohlcv_by_date(start, end, symbol)
        if df.empty:
            raise ValueError("no ohlcv")
        close = df["종가"].astype(float)
        volume = df["거래량"].astype(float)
        price = float(close.iloc[-1])
        change_pct = float(df["등락률"].iloc[-1]) if "등락률" in df else 0.0
        items.extend(_technical_items(close, volume))
    except Exception:  # noqa: BLE001
        logger.exception("technical evidence failed for %s", symbol)
        gaps.append("technical")

    # ── 수급 축 ──────────────────────────────────────────────────
    try:
        flow_start = (date.fromisoformat(as_of) - timedelta(days=40)).strftime("%Y%m%d")
        fdf = stock.get_market_trading_value_by_date(flow_start, end, symbol)
        if fdf.empty:
            raise ValueError("no flow data")
        items.extend(_flow_items(fdf))
    except Exception:  # noqa: BLE001
        logger.exception("flow evidence failed for %s", symbol)
        gaps.append("flow")

    return StockEvidence(
        symbol=symbol, name=name, market="KR", as_of=as_of,
        price=price, change_pct=change_pct, items=items, gaps=gaps,
    )


# ── 파생지표 계산 (결정론적 — LLM 미개입) ─────────────────────────


def _technical_items(close, volume) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    price = float(close.iloc[-1])

    # 이동평균 배열
    for window in (5, 20, 60):
        if len(close) < window:
            continue
        ma = float(close.tail(window).mean())
        gap_pct = (price - ma) / ma * 100
        items.append(EvidenceItem(
            key=f"tech.ma{window}", category="technical", label=f"MA{window} 대비",
            value=round(gap_pct, 1), unit="%", detail=f"MA{window}={ma:,.0f}",
            direction="bullish" if gap_pct > 0 else "bearish",
        ))

    # RSI(14)
    if len(close) >= 15:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        direction = "bearish" if rsi > 70 else ("bullish" if rsi < 30 else "neutral")
        items.append(EvidenceItem(
            key="tech.rsi14", category="technical", label="RSI(14)",
            value=round(rsi, 1), direction=direction,
            detail="과매수>70, 과매도<30",
        ))

    # 거래량 배수 (20일 평균 대비)
    if len(volume) >= 21:
        avg20 = float(volume.tail(21).head(20).mean())
        if avg20 > 0:
            mult = float(volume.iloc[-1]) / avg20
            items.append(EvidenceItem(
                key="tech.vol_mult", category="technical", label="거래량 (20일 평균 대비)",
                value=round(mult, 1), unit="배",
                direction="bullish" if mult >= 2 else "neutral",
            ))

    # 52주 위치
    if len(close) >= 240:
        year = close.tail(240)
        low, high = float(year.min()), float(year.max())
        if high > low:
            pos = (price - low) / (high - low) * 100
            items.append(EvidenceItem(
                key="tech.52w_pos", category="technical", label="52주 밴드 내 위치",
                value=round(pos, 0), unit="%",
                detail=f"저 {low:,.0f} ~ 고 {high:,.0f}",
                direction="bullish" if pos >= 80 else ("bearish" if pos <= 20 else "neutral"),
            ))

    # 단기 수익률
    for days, key in ((5, "tech.ret5d"), (20, "tech.ret20d")):
        if len(close) > days:
            ret = (price / float(close.iloc[-days - 1]) - 1) * 100
            items.append(EvidenceItem(
                key=key, category="technical", label=f"{days}일 수익률",
                value=round(ret, 1), unit="%",
                direction="bullish" if ret > 0 else "bearish",
            ))
    return items


def _flow_items(fdf) -> list[EvidenceItem]:
    """투자자별 순매수 — 외인/기관 누적·연속일수 (단위: 억원)."""
    items: list[EvidenceItem] = []
    to_eok = 1e8

    for column, key_prefix, label in (
        ("외국인합계", "flow.foreign", "외국인"),
        ("기관합계", "flow.inst", "기관"),
    ):
        if column not in fdf.columns:
            continue
        series = fdf[column].astype(float)

        net5 = float(series.tail(5).sum()) / to_eok
        items.append(EvidenceItem(
            key=f"{key_prefix}_net5d", category="flow", label=f"{label} 5일 순매수",
            value=round(net5, 0), unit="억",
            direction="bullish" if net5 > 0 else "bearish",
        ))

        # 연속 순매수/순매도 일수
        streak = 0
        sign = 1 if float(series.iloc[-1]) > 0 else -1
        for value in reversed(series.tolist()):
            if (value > 0) == (sign > 0) and value != 0:
                streak += 1
            else:
                break
        word = "순매수" if sign > 0 else "순매도"
        items.append(EvidenceItem(
            key=f"{key_prefix}_streak", category="flow", label=f"{label} 연속 {word}",
            value=streak, unit="일",
            direction=("bullish" if sign > 0 else "bearish") if streak >= 3 else "neutral",
        ))
    return items
