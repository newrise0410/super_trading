from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from aim.storage.repositories.base import BaseRepository


class ReportsRepository(BaseRepository):
    def save(self, kind: str, market: str, master_md: str, data: dict[str, Any]) -> str:
        report_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO reports (report_id, kind, market, master_md, data_json, status)"
            " VALUES (?, ?, ?, ?, ?, 'published')",
            (report_id, kind, market, master_md, json.dumps(data, ensure_ascii=False)),
        )
        self.conn.commit()
        return report_id

    def latest(self, kind: str | None = None) -> sqlite3.Row | None:
        if kind:
            cur = self.conn.execute(
                "SELECT * FROM reports WHERE kind = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (kind,),
            )
        else:
            cur = self.conn.execute("SELECT * FROM reports ORDER BY created_at DESC, id DESC LIMIT 1")
        return cur.fetchone()
