from __future__ import annotations

import sqlite3

from aim.storage.repositories.base import BaseRepository


class PortfolioRepository(BaseRepository):
    """내 실제 보유 종목 CRUD."""

    def upsert(
        self, symbol: str, quantity: float, avg_price: float,
        *, name: str = "", market: str = "KR", memo: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO portfolio_positions (symbol, name, market, quantity, avg_price, memo)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(symbol) DO UPDATE SET"
            " name = CASE WHEN excluded.name != '' THEN excluded.name ELSE name END,"
            " quantity = excluded.quantity, avg_price = excluded.avg_price,"
            " memo = CASE WHEN excluded.memo != '' THEN excluded.memo ELSE memo END,"
            " updated_at = datetime('now')",
            (symbol, name, market, quantity, avg_price, memo),
        )
        self.conn.commit()

    def remove(self, symbol: str) -> None:
        self.conn.execute("DELETE FROM portfolio_positions WHERE symbol = ?", (symbol,))
        self.conn.commit()

    def replace_all(self, positions: list[dict]) -> None:
        """KIS 동기화용 — 전체 교체 (계좌가 진실의 원천)."""
        self.conn.execute("DELETE FROM portfolio_positions")
        for p in positions:
            self.conn.execute(
                "INSERT INTO portfolio_positions (symbol, name, quantity, avg_price)"
                " VALUES (?, ?, ?, ?)",
                (p["symbol"], p.get("name", ""), p["quantity"], p["avg_price"]),
            )
        self.conn.commit()

    def list_all(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM portfolio_positions ORDER BY quantity * avg_price DESC"
        ).fetchall()
