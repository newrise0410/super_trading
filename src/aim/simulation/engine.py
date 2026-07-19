"""전략 시뮬레이션 엔진 v1 — 마감 사이클 (PLAN.md §5, Alpha Arena 감사추적 개념).

전략 3종 (각 독립 가상 1억, 종가 체결, 소수점 수량 허용):
- benchmark: KODEX200(069500) 전액 바이앤홀드 — 비교 기준
- momentum:  특징주(개별종목·거래대금 필터) 상위 매수, 손절 -7% / 익절 +15%
- ai_debate: 당일 AI 토론 판단(BUY 확신도≥0.7) 추종, AVOID면 청산, 손절 -7%

모든 거래는 decision_id로 판단 로그에 연결(감사 추적). 사이클마다 평가액 기록 → MDD·수익률.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable

from aim.data.models import MarketSnapshot
from aim.storage.repositories.simulation import SimulationRepository

logger = logging.getLogger(__name__)

INITIAL_CASH = 100_000_000.0   # 1억
MAX_SLOTS = 10
SLOT_FRACTION = 0.10
STOP_PCT = -7.0
TARGET_PCT = 15.0
BENCHMARK_SYMBOL = "069500"    # KODEX 200
MOMENTUM_MIN_CHANGE = 3.0      # 진입 최소 등락률
MOMENTUM_MIN_VALUE = 500.0     # 진입 최소 거래대금 (억)

STRATEGIES = ("benchmark", "momentum", "ai_debate")

PriceFn = Callable[[str], tuple[float, float] | None]  # (symbol) -> (price, change%)


def run_close_cycle(
    conn: sqlite3.Connection, snapshot: MarketSnapshot, last_price: PriceFn, date: str
) -> tuple[dict[str, float], list[dict]]:
    """모든 전략의 마감 사이클 실행 → ({strategy: 평가액}, 이번 사이클 체결 목록)."""
    repo = SimulationRepository(conn)
    values: dict[str, float] = {}
    last_trade_id = conn.execute(
        "SELECT COALESCE(MAX(id), 0) AS m FROM virtual_trades"
    ).fetchone()["m"]

    for strategy in STRATEGIES:
        pf = repo.ensure_portfolio(strategy, "KR", INITIAL_CASH)
        try:
            _run_strategy(repo, pf, strategy, conn, snapshot, last_price, date)
        except Exception:  # noqa: BLE001 — 전략별 실패 격리
            logger.exception("strategy %s cycle failed", strategy)
        values[strategy] = _mark_equity(repo, pf["id"], last_price, date)

    trades = [dict(r) for r in conn.execute(
        "SELECT t.side, t.symbol, t.quantity, t.price, p.strategy"
        " FROM virtual_trades t JOIN virtual_portfolios p ON p.id = t.portfolio_id"
        " WHERE t.id > ? ORDER BY t.id", (last_trade_id,),
    )]
    return values, trades


# ── 전략별 사이클 ─────────────────────────────────────────────────


def _run_strategy(repo, pf, strategy, conn, snapshot, last_price, date) -> None:
    if strategy == "benchmark":
        _benchmark(repo, pf, last_price)
    elif strategy == "momentum":
        _exits(repo, pf, last_price)
        _momentum_entries(repo, pf, snapshot, last_price)
    elif strategy == "ai_debate":
        _ai_exits(repo, pf, conn, last_price, date)
        _ai_entries(repo, pf, conn, last_price, date)


def _benchmark(repo, pf, last_price) -> None:
    if repo.positions(pf["id"]):
        return
    quote = last_price(BENCHMARK_SYMBOL)
    if not quote:
        return
    cash = repo.cash(pf["id"])
    if cash > 0:
        repo.execute_trade(pf["id"], BENCHMARK_SYMBOL, "BUY", cash / quote[0], quote[0])


def _exits(repo, pf, last_price) -> None:
    """손절 -7% / 익절 +15% (종가 기준 — prism-insight 종가 룰 개념)."""
    for pos in repo.positions(pf["id"]):
        quote = last_price(pos["symbol"])
        if not quote:
            continue
        pnl_pct = (quote[0] / pos["avg_price"] - 1) * 100
        if pnl_pct <= STOP_PCT or pnl_pct >= TARGET_PCT:
            repo.execute_trade(pf["id"], pos["symbol"], "SELL", pos["quantity"], quote[0])


def _momentum_entries(repo, pf, snapshot, last_price) -> None:
    held = {p["symbol"] for p in repo.positions(pf["id"])}
    if len(held) >= MAX_SLOTS:
        return
    budget = INITIAL_CASH * SLOT_FRACTION
    for move in snapshot.top_gainers:
        if move.symbol in held or move.change_pct < MOMENTUM_MIN_CHANGE or move.value < MOMENTUM_MIN_VALUE:
            continue
        if repo.cash(pf["id"]) < budget:
            break
        repo.execute_trade(pf["id"], move.symbol, "BUY", budget / move.close, move.close)
        held.add(move.symbol)
        if len(held) >= MAX_SLOTS:
            break


def _todays_decisions(conn, date: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM decisions WHERE strategy = 'ai_debate_v1' AND date(created_at) = ?"
        " ORDER BY created_at",
        (date,),
    ).fetchall()


def _ai_exits(repo, pf, conn, last_price, date) -> None:
    _exits(repo, pf, last_price)  # 공통 손절/익절
    avoid = {d["symbol"]: d["decision_id"] for d in _todays_decisions(conn, date) if d["action"] == "AVOID"}
    for pos in repo.positions(pf["id"]):
        if pos["symbol"] in avoid:
            quote = last_price(pos["symbol"])
            if quote:
                repo.execute_trade(
                    pf["id"], pos["symbol"], "SELL", pos["quantity"], quote[0],
                    decision_id=avoid[pos["symbol"]],
                )


def _ai_entries(repo, pf, conn, last_price, date) -> None:
    held = {p["symbol"] for p in repo.positions(pf["id"])}
    budget = INITIAL_CASH * SLOT_FRACTION
    for d in _todays_decisions(conn, date):
        if d["action"] != "BUY" or (d["confidence"] or 0) < 0.7 or d["symbol"] in held:
            continue
        if len(held) >= MAX_SLOTS or repo.cash(pf["id"]) < budget:
            break
        quote = last_price(d["symbol"])
        if not quote:
            continue
        repo.execute_trade(
            pf["id"], d["symbol"], "BUY", budget / quote[0], quote[0],
            decision_id=d["decision_id"],
        )
        held.add(d["symbol"])


def _mark_equity(repo, portfolio_id: int, last_price, date: str) -> float:
    value = repo.cash(portfolio_id)
    for pos in repo.positions(portfolio_id):
        quote = last_price(pos["symbol"])
        price = quote[0] if quote else pos["avg_price"]  # 시세 실패 시 보수적으로 평단가
        value += pos["quantity"] * price
    repo.record_equity(portfolio_id, date, value)
    return value


# ── 리더보드 ─────────────────────────────────────────────────────


def render_leaderboard(conn: sqlite3.Connection) -> str:
    repo = SimulationRepository(conn)
    rows = []
    for strategy in STRATEGIES:
        pf = conn.execute(
            "SELECT * FROM virtual_portfolios WHERE strategy = ?", (strategy,)
        ).fetchone()
        if pf is None:
            continue
        series = [r["value"] for r in repo.equity_series(pf["id"])]
        if not series:
            continue
        total_ret = (series[-1] / pf["initial_cash"] - 1) * 100
        peak, mdd = series[0], 0.0
        for v in series:
            peak = max(peak, v)
            mdd = min(mdd, (v / peak - 1) * 100)
        rows.append((strategy, total_ret, mdd, repo.trade_count(pf["id"]), series[-1]))

    if not rows:
        return ""
    rows.sort(key=lambda r: r[1], reverse=True)
    label = {"ai_debate": "AI 토론", "momentum": "모멘텀", "benchmark": "벤치마크(K200)"}
    lines = ["## 🏁 전략 시뮬레이션 리더보드 (가상 1억)"]
    for i, (strategy, ret, mdd, trades, value) in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(
            f"{medal} **{label.get(strategy, strategy)}** 수익률 {ret:+.2f}% · MDD {mdd:.1f}%"
            f" · 거래 {trades}건 · 평가 {value:,.0f}원"
        )
    return "\n".join(lines)
