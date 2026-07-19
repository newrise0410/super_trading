from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from aim.storage.repositories.base import BaseRepository


class DecisionsRepository(BaseRepository):
    """판단 로그 — Q&A(/why, /prob)와 확률 캘리브레이션의 원천 (PLAN.md §10.6-4)."""

    def save(
        self,
        *,
        market: str,
        symbol: str,
        name: str,
        action: str,
        strategy: str,
        confidence: float | None = None,
        horizon: str | None = None,
        entry_price: float | None = None,
        target_price: float | None = None,
        stop_price: float | None = None,
        rationale: list[dict[str, Any]] | None = None,
        risks: list[dict[str, Any]] | None = None,
        debate_log: list[dict[str, Any]] | None = None,
        data_snapshot: dict[str, Any] | None = None,
        report_id: str | None = None,
    ) -> str:
        decision_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO decisions (
                decision_id, market, symbol, name, action, confidence, horizon,
                entry_price, target_price, stop_price, strategy,
                rationale_json, risks_json, debate_log_json, data_snapshot_json, report_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id, market, symbol, name, action, confidence, horizon,
                entry_price, target_price, stop_price, strategy,
                json.dumps(rationale or [], ensure_ascii=False),
                json.dumps(risks or [], ensure_ascii=False),
                json.dumps(debate_log or [], ensure_ascii=False),
                json.dumps(data_snapshot or {}, ensure_ascii=False),
                report_id,
            ),
        )
        self.conn.commit()
        return decision_id

    def history(self, symbol: str, limit: int = 20) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM decisions WHERE symbol = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (symbol, limit),
        )
        return cur.fetchall()

    def latest_for_symbol(self, symbol: str) -> sqlite3.Row | None:
        rows = self.history(symbol, limit=1)
        return rows[0] if rows else None
