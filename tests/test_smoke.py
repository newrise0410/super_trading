"""스모크 테스트 — mock 경로는 외부 의존성 없이 전 파이프라인이 돌아야 한다."""

import sqlite3

from aim.data.provider import MockKRProvider
from aim.reports.master import build_kr_close_briefing
from aim.storage import db
from aim.storage.repositories.decisions import DecisionsRepository
from aim.storage.repositories.reports import ReportsRepository


def test_mock_briefing_contains_core_sections():
    snap = MockKRProvider().close_snapshot("2026-07-18")
    md = build_kr_close_briefing(snap)
    assert "KOSPI" in md
    assert "수급" in md
    assert "특징주" in md
    assert "투자 자문이 아닙니다" in md


def test_migrations_and_repositories(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    try:
        applied = db.migrate(conn)
        assert "001_init.sql" in applied

        report_id = ReportsRepository(conn).save("kr_close", "KR", "# test", {"a": 1})
        row = ReportsRepository(conn).latest("kr_close")
        assert row["report_id"] == report_id

        decisions = DecisionsRepository(conn)
        decision_id = decisions.save(
            market="KR", symbol="005930", name="삼성전자", action="WATCH",
            strategy="rule_v1", confidence=0.7,
            rationale=[{"type": "flow", "text": "외인 5일 연속 순매수", "weight": 0.5}],
            data_snapshot={"close": 71000},
        )
        latest = decisions.latest_for_symbol("005930")
        assert latest["decision_id"] == decision_id
        assert latest["action"] == "WATCH"
    finally:
        conn.close()


def test_migrate_idempotent(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    try:
        db.migrate(conn)
        assert db.migrate(conn) == []  # 두 번째 적용은 no-op
    finally:
        conn.close()
