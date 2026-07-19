from __future__ import annotations

import sqlite3


class BaseRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
