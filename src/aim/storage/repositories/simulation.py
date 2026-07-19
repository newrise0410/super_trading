from __future__ import annotations

import sqlite3

from aim.storage.repositories.base import BaseRepository


class SimulationRepository(BaseRepository):
    """가상 포트폴리오 상태 — 모든 거래는 decision_id로 판단에 연결 가능 (감사 추적)."""

    def ensure_portfolio(self, strategy: str, market: str, initial_cash: float) -> sqlite3.Row:
        self.conn.execute(
            "INSERT OR IGNORE INTO virtual_portfolios (strategy, market, initial_cash, cash)"
            " VALUES (?, ?, ?, ?)",
            (strategy, market, initial_cash, initial_cash),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT * FROM virtual_portfolios WHERE strategy = ?", (strategy,)
        ).fetchone()

    def positions(self, portfolio_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM virtual_positions WHERE portfolio_id = ?", (portfolio_id,)
        ).fetchall()

    def execute_trade(
        self, portfolio_id: int, symbol: str, side: str, quantity: float, price: float,
        *, decision_id: str | None = None,
    ) -> None:
        """체결 + 포지션·현금 갱신. side: BUY | SELL (SELL은 전량 기준 수량 전달)."""
        cost = quantity * price
        row = self.conn.execute(
            "SELECT * FROM virtual_positions WHERE portfolio_id = ? AND symbol = ?",
            (portfolio_id, symbol),
        ).fetchone()

        if side == "BUY":
            if row:
                new_qty = row["quantity"] + quantity
                new_avg = (row["quantity"] * row["avg_price"] + cost) / new_qty
                self.conn.execute(
                    "UPDATE virtual_positions SET quantity = ?, avg_price = ? WHERE id = ?",
                    (new_qty, new_avg, row["id"]),
                )
            else:
                self.conn.execute(
                    "INSERT INTO virtual_positions (portfolio_id, symbol, quantity, avg_price)"
                    " VALUES (?, ?, ?, ?)",
                    (portfolio_id, symbol, quantity, price),
                )
            self.conn.execute(
                "UPDATE virtual_portfolios SET cash = cash - ? WHERE id = ?", (cost, portfolio_id)
            )
        else:  # SELL
            if not row:
                raise ValueError(f"no position to sell: {symbol}")
            remaining = row["quantity"] - quantity
            if remaining <= 1e-9:
                self.conn.execute("DELETE FROM virtual_positions WHERE id = ?", (row["id"],))
            else:
                self.conn.execute(
                    "UPDATE virtual_positions SET quantity = ? WHERE id = ?", (remaining, row["id"])
                )
            self.conn.execute(
                "UPDATE virtual_portfolios SET cash = cash + ? WHERE id = ?", (cost, portfolio_id)
            )

        self.conn.execute(
            "INSERT INTO virtual_trades (portfolio_id, decision_id, symbol, side, quantity, price)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (portfolio_id, decision_id, symbol, side, quantity, price),
        )
        self.conn.commit()

    def cash(self, portfolio_id: int) -> float:
        return float(self.conn.execute(
            "SELECT cash FROM virtual_portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()["cash"])

    def record_equity(self, portfolio_id: int, date: str, value: float) -> None:
        self.conn.execute(
            "INSERT INTO sim_equity (portfolio_id, date, value) VALUES (?, ?, ?)"
            " ON CONFLICT(portfolio_id, date) DO UPDATE SET value = excluded.value",
            (portfolio_id, date, value),
        )
        self.conn.commit()

    def equity_series(self, portfolio_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT date, value FROM sim_equity WHERE portfolio_id = ? ORDER BY date",
            (portfolio_id,),
        ).fetchall()

    def trade_count(self, portfolio_id: int) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM virtual_trades WHERE portfolio_id = ?", (portfolio_id,)
        ).fetchone()["n"])
