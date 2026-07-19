"""내 포트폴리오 — 평가·렌더 (실보유. 시뮬레이션 virtual_*와 별개).

- 통화 인지: KR=KRW, US=USD — 통화별 합계 분리, 환율(fx) 제공 시 원화 통합 합계
- 평단가 미상(avg_price<=0): 손익 표시 생략 (왜곡 방지), 평가액·비중은 계산
- 시세 조회 실패 종목 격리: 합계가 불완전하면 통합 합계 생략 (거짓 합계 방지)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

# (symbol, market) -> (현재가, 당일등락률%) | None
PriceLookup = Callable[[str, str], tuple[float, float] | None]

_CURRENCY = {"KR": "KRW", "US": "USD"}


@dataclass(frozen=True)
class PositionView:
    symbol: str
    name: str
    market: str
    currency: str
    quantity: float
    avg_price: float          # 0 = 매입가 미상
    price: float | None
    change_pct: float | None
    value: float | None
    pnl: float | None         # 평단가 미상이면 None
    pnl_pct: float | None
    weight_pct: float | None  # 원화 환산 기준 (fx 없으면 None)


def value_portfolio(
    rows, lookup: PriceLookup, fx_usdkrw: float | None = None
) -> tuple[list[PositionView], dict]:
    views: list[PositionView] = []
    by_currency: dict[str, dict[str, float | None]] = {}
    all_priced = True
    all_basis = True

    for row in rows:
        market = row["market"] or "KR"
        currency = _CURRENCY.get(market, "KRW")
        quote = lookup(row["symbol"], market)
        price, change = (quote if quote else (None, None))
        basis_known = row["avg_price"] > 0

        value = pnl = pnl_pct = None
        if price is not None:
            value = row["quantity"] * price
            if basis_known:
                cost = row["quantity"] * row["avg_price"]
                pnl = value - cost
                pnl_pct = (price / row["avg_price"] - 1) * 100
        else:
            all_priced = False
        if not basis_known:
            all_basis = False

        bucket = by_currency.setdefault(currency, {"value": 0.0, "pnl": 0.0})
        if value is not None:
            bucket["value"] += value  # type: ignore[operator]
            if pnl is not None and bucket["pnl"] is not None:
                bucket["pnl"] += pnl  # type: ignore[operator]

        views.append(PositionView(
            row["symbol"], row["name"] or row["symbol"], market, currency,
            row["quantity"], row["avg_price"], price, change, value, pnl, pnl_pct, None,
        ))

    # 원화 환산 통합 (모든 종목 시세 확보 + 환율 제공 시)
    combined_krw = None
    if all_priced and views:
        needs_fx = any(v.currency == "USD" for v in views)
        if not needs_fx or fx_usdkrw:
            combined_krw = sum(
                (v.value or 0) * (fx_usdkrw if v.currency == "USD" else 1.0)  # type: ignore[operator]
                for v in views
            )
            if combined_krw:
                views = [
                    replace(v, weight_pct=(
                        (v.value or 0) * (fx_usdkrw if v.currency == "USD" else 1.0) / combined_krw * 100  # type: ignore[operator]
                    ))
                    for v in views
                ]

    totals = {
        "by_currency": by_currency,
        "combined_krw": combined_krw,
        "all_priced": all_priced,
        "all_basis": all_basis,
        "fx_usdkrw": fx_usdkrw,
    }
    return views, totals


def _money(value: float, currency: str) -> str:
    return f"${value:,.2f}" if currency == "USD" else f"{value:,.0f}원"


def render_portfolio_md(views: list[PositionView], totals: dict) -> str:
    if not views:
        return ""
    lines = ["## 💼 내 포트폴리오"]

    for v in sorted(views, key=lambda x: -(x.weight_pct or 0)):
        if v.price is None:
            lines.append(f"- **{v.name}** {v.quantity:g}주 (시세 조회 불가)")
            continue
        arrow = "🔺" if (v.change_pct or 0) > 0 else ("🔻" if (v.change_pct or 0) < 0 else "➖")
        parts = [
            f"- **{v.name}** {v.quantity:g}주 · {_money(v.price, v.currency)} {arrow}{(v.change_pct or 0):+.2f}%",
            f"평가 {_money(v.value or 0, v.currency)}",
        ]
        if v.pnl is not None:
            parts.append(f"손익 {v.pnl:+,.2f} ({v.pnl_pct:+.1f}%)")
        if v.weight_pct is not None:
            parts.append(f"비중 {v.weight_pct:.0f}%")
        lines.append(" · ".join(parts))

    summary = []
    for currency, bucket in totals["by_currency"].items():
        summary.append(f"{currency} 평가 {_money(bucket['value'], currency)}")
    if totals["combined_krw"] is not None:
        fx_note = f" (환율 {totals['fx_usdkrw']:,.0f})" if totals.get("fx_usdkrw") else ""
        summary.append(f"**통합 {totals['combined_krw']:,.0f}원**{fx_note}")
    if summary:
        lines.append("\n**합계** " + " · ".join(summary))
    if not totals["all_basis"]:
        lines.append("_일부 종목 평단가 미입력 — 손익은 입력된 종목만 표시_")
    return "\n".join(lines)
