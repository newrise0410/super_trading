"""전략 시뮬레이션 — 진입·청산 룰, 감사 추적, 평가액·리더보드 검증."""

import pytest

from aim.data.models import MarketSnapshot, StockMove
from aim.simulation.engine import (
    BENCHMARK_SYMBOL,
    INITIAL_CASH,
    render_leaderboard,
    run_close_cycle,
)
from aim.storage import db
from aim.storage.repositories.decisions import DecisionsRepository


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    yield c
    c.close()


PRICES = {
    BENCHMARK_SYMBOL: (30000.0, 0.5),
    "005930": (70000.0, 3.5),
    "111111": (10000.0, 5.0),
    "222222": (5000.0, 4.0),
}


def _lookup(symbol):
    return PRICES.get(symbol)


def _snap(gainers=()):
    return MarketSnapshot(market="KR", date="2026-07-20", session="close",
                          top_gainers=list(gainers))


def test_benchmark_all_in_once(conn):
    _, trades1 = run_close_cycle(conn, _snap(), _lookup, "2026-07-20")
    _, trades2 = run_close_cycle(conn, _snap(), _lookup, "2026-07-21")  # 재실행에도 중복 매수 없음

    # 체결 수집 — 첫 사이클만 벤치마크 매수 1건, 이후 없음
    assert [(t["strategy"], t["side"], t["symbol"]) for t in trades1] == [
        ("benchmark", "BUY", BENCHMARK_SYMBOL)
    ]
    assert trades2 == []

    pf = conn.execute("SELECT * FROM virtual_portfolios WHERE strategy='benchmark'").fetchone()
    pos = conn.execute(
        "SELECT * FROM virtual_positions WHERE portfolio_id=?", (pf["id"],)
    ).fetchall()
    assert len(pos) == 1 and pos[0]["symbol"] == BENCHMARK_SYMBOL
    assert pos[0]["quantity"] * 30000 == pytest.approx(INITIAL_CASH)
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM virtual_trades WHERE portfolio_id=?", (pf["id"],)
    ).fetchone()["n"] == 1


def test_momentum_entry_filters(conn):
    gainers = [
        StockMove("111111", "강한종목", 10000, +5.0, 800),   # 통과
        StockMove("222222", "약한등락", 5000, +2.0, 900),    # 등락률 미달
        StockMove("333333", "저유동성", 3000, +8.0, 100),    # 거래대금 미달
    ]
    run_close_cycle(conn, _snap(gainers), _lookup, "2026-07-20")

    pf = conn.execute("SELECT * FROM virtual_portfolios WHERE strategy='momentum'").fetchone()
    pos = conn.execute(
        "SELECT symbol FROM virtual_positions WHERE portfolio_id=?", (pf["id"],)
    ).fetchall()
    assert [p["symbol"] for p in pos] == ["111111"]


def test_momentum_stop_loss_exit(conn):
    gainers = [StockMove("111111", "종목", 10000, +5.0, 800)]
    run_close_cycle(conn, _snap(gainers), _lookup, "2026-07-20")

    PRICES["111111"] = (9200.0, -8.0)  # -8% → 손절
    try:
        run_close_cycle(conn, _snap(), _lookup, "2026-07-21")
    finally:
        PRICES["111111"] = (10000.0, 5.0)

    pf = conn.execute("SELECT * FROM virtual_portfolios WHERE strategy='momentum'").fetchone()
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM virtual_positions WHERE portfolio_id=?", (pf["id"],)
    ).fetchone()["n"] == 0
    sells = conn.execute(
        "SELECT * FROM virtual_trades WHERE portfolio_id=? AND side='SELL'", (pf["id"],)
    ).fetchall()
    assert len(sells) == 1 and sells[0]["price"] == 9200.0


def test_ai_debate_follows_decisions_with_audit_link(conn):
    decision_id = DecisionsRepository(conn).save(
        market="KR", symbol="005930", name="삼성전자", action="BUY",
        strategy="ai_debate_v1", confidence=0.72,
    )
    DecisionsRepository(conn).save(  # 확신도 미달 → 무시
        market="KR", symbol="111111", name="저확신", action="BUY",
        strategy="ai_debate_v1", confidence=0.5,
    )
    from datetime import date as d
    today = d.today().isoformat()
    run_close_cycle(conn, _snap(), _lookup, today)

    pf = conn.execute("SELECT * FROM virtual_portfolios WHERE strategy='ai_debate'").fetchone()
    pos = conn.execute(
        "SELECT * FROM virtual_positions WHERE portfolio_id=?", (pf["id"],)
    ).fetchall()
    assert [p["symbol"] for p in pos] == ["005930"]
    trade = conn.execute(
        "SELECT * FROM virtual_trades WHERE portfolio_id=?", (pf["id"],)
    ).fetchone()
    assert trade["decision_id"] == decision_id  # 감사 추적 연결


def test_equity_and_leaderboard(conn):
    run_close_cycle(conn, _snap(), _lookup, "2026-07-20")

    PRICES[BENCHMARK_SYMBOL] = (33000.0, 1.0)  # 벤치마크 +10%
    try:
        run_close_cycle(conn, _snap(), _lookup, "2026-07-21")
    finally:
        PRICES[BENCHMARK_SYMBOL] = (30000.0, 0.5)

    board = render_leaderboard(conn)
    assert "리더보드" in board
    assert "벤치마크(K200)" in board and "+10.00%" in board
    assert board.index("벤치마크") < board.index("모멘텀")  # 수익률순 정렬 (모멘텀 0%)
