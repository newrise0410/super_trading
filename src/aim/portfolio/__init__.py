"""내 포트폴리오 — 평가·렌더 (실보유. 시뮬레이션 virtual_*와 별개)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# (symbol) -> (현재가, 당일등락률%) | None (조회 불가)
PriceLookup = Callable[[str], tuple[float, float] | None]


@dataclass(frozen=True)
class PositionView:
    symbol: str
    name: str
    quantity: float
    avg_price: float
    price: float | None       # None = 시세 조회 불가
    change_pct: float | None
    value: float | None       # 평가액
    pnl: float | None         # 평가손익
    pnl_pct: float | None
    weight_pct: float | None  # 포트폴리오 내 비중


def value_portfolio(rows, lookup: PriceLookup) -> tuple[list[PositionView], dict]:
    views: list[PositionView] = []
    total_value = total_cost = 0.0
    priced_all = True

    for row in rows:
        quote = lookup(row["symbol"])
        price, change = (quote if quote else (None, None))
        value = pnl = pnl_pct = None
        cost = row["quantity"] * row["avg_price"]
        if price is not None:
            value = row["quantity"] * price
            pnl = value - cost
            pnl_pct = (price / row["avg_price"] - 1) * 100 if row["avg_price"] else 0.0
            total_value += value
        else:
            priced_all = False
        total_cost += cost
        views.append(PositionView(
            row["symbol"], row["name"] or row["symbol"], row["quantity"], row["avg_price"],
            price, change, value, pnl, pnl_pct, None,
        ))

    if total_value > 0:
        views = [
            v if v.value is None else PositionView(
                v.symbol, v.name, v.quantity, v.avg_price, v.price, v.change_pct,
                v.value, v.pnl, v.pnl_pct, v.value / total_value * 100,
            )
            for v in views
        ]
    totals = {
        "cost": total_cost,
        "value": total_value if priced_all else None,
        "pnl": (total_value - total_cost) if priced_all else None,
        "pnl_pct": ((total_value / total_cost - 1) * 100) if priced_all and total_cost else None,
    }
    return views, totals


def render_portfolio_md(views: list[PositionView], totals: dict) -> str:
    if not views:
        return ""
    lines = ["## 💼 내 포트폴리오"]
    for v in views:
        if v.price is not None:
            arrow = "🔺" if (v.change_pct or 0) > 0 else ("🔻" if (v.change_pct or 0) < 0 else "➖")
            lines.append(
                f"- **{v.name}** {v.quantity:,.0f}주 · {v.price:,.0f} {arrow}{(v.change_pct or 0):+.2f}%"
                f" · 손익 {v.pnl:+,.0f} ({v.pnl_pct:+.1f}%) · 비중 {v.weight_pct or 0:.0f}%"
            )
        else:
            lines.append(
                f"- **{v.name}** {v.quantity:,.0f}주 @ {v.avg_price:,.0f} (시세 조회 불가)"
            )
    if totals["value"] is not None:
        lines.append(
            f"\n**합계** 평가 {totals['value']:,.0f} · 손익 {totals['pnl']:+,.0f} ({totals['pnl_pct']:+.1f}%)"
        )
    return "\n".join(lines)
