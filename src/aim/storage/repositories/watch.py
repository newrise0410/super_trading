from __future__ import annotations

import json
import sqlite3
import uuid

from aim.storage.repositories.base import BaseRepository
from aim.watch.models import Signal


class WatchlistRepository(BaseRepository):
    def add(self, symbol: str, name: str = "", market: str = "KR") -> None:
        self.conn.execute(
            "INSERT INTO watchlist (symbol, name, market, active) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(symbol) DO UPDATE SET name = excluded.name, active = 1",
            (symbol, name, market),
        )
        self.conn.commit()

    def remove(self, symbol: str) -> None:
        self.conn.execute("UPDATE watchlist SET active = 0 WHERE symbol = ?", (symbol,))
        self.conn.commit()

    def list_active(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM watchlist WHERE active = 1 ORDER BY added_at"
        ).fetchall()


class SignalsRepository(BaseRepository):
    def save(self, signal: Signal, fired_at: str, *, delivered: bool) -> str:
        signal_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO signals (signal_id, symbol, kind, severity, message, payload_json, fired_at, delivered)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                signal_id, signal.symbol, signal.kind, signal.severity, signal.message,
                json.dumps(signal.payload, ensure_ascii=False), fired_at, int(delivered),
            ),
        )
        self.conn.commit()
        return signal_id

    def last_fired(self, symbol: str, kind: str) -> str | None:
        row = self.conn.execute(
            "SELECT fired_at FROM signals WHERE symbol = ? AND kind = ? ORDER BY fired_at DESC LIMIT 1",
            (symbol, kind),
        ).fetchone()
        return row["fired_at"] if row else None

    def recent(self, symbol: str, kind: str, since: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM signals WHERE symbol = ? AND kind = ? AND fired_at >= ? ORDER BY fired_at DESC",
            (symbol, kind, since),
        ).fetchall()


class ObservationsRepository(BaseRepository):
    """장중 폴링 관측치 — 시간대별 누적거래량 축적 (baseline 학습의 원천)."""

    def record(self, symbol: str, obs_date: str, time_slot: str, cum_volume: float) -> None:
        self.conn.execute(
            "INSERT INTO intraday_observations (symbol, obs_date, time_slot, cum_volume)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(symbol, obs_date, time_slot) DO UPDATE SET cum_volume = excluded.cum_volume",
            (symbol, obs_date, time_slot, cum_volume),
        )
        self.conn.commit()


class BaselineRepository(BaseRepository):
    def upsert(self, symbol: str, time_slot: str, avg: float, std: float, days: int) -> None:
        self.conn.execute(
            "INSERT INTO volume_baselines (symbol, time_slot, avg_cum_volume, std_cum_volume, days)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(symbol, time_slot) DO UPDATE SET"
            " avg_cum_volume = excluded.avg_cum_volume, std_cum_volume = excluded.std_cum_volume,"
            " days = excluded.days, updated_at = datetime('now')",
            (symbol, time_slot, avg, std, days),
        )
        self.conn.commit()

    def get(self, symbol: str, time_slot: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM volume_baselines WHERE symbol = ? AND time_slot = ?",
            (symbol, time_slot),
        ).fetchone()
