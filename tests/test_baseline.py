"""관측치 축적 → baseline 재계산 검증."""

from datetime import date, datetime, timedelta

import pytest

from aim.storage import db
from aim.storage.repositories.watch import BaselineRepository, ObservationsRepository
from aim.watch.baseline import rebuild_baselines


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    yield c
    c.close()


def _past(days):
    return (date.today() - timedelta(days=days)).isoformat()


def test_rebuild_computes_avg_std(conn):
    obs = ObservationsRepository(conn)
    for d, vol in [(5, 1000.0), (4, 1100.0), (3, 900.0), (2, 1000.0)]:
        obs.record("005930", _past(d), "10:00", vol)

    updated = rebuild_baselines(conn)
    assert updated == 1
    row = BaselineRepository(conn).get("005930", "10:00")
    assert row["avg_cum_volume"] == pytest.approx(1000.0)
    assert row["days"] == 4
    assert row["std_cum_volume"] > 0


def test_rebuild_skips_insufficient_samples(conn):
    obs = ObservationsRepository(conn)
    obs.record("005930", _past(2), "10:00", 1000.0)
    obs.record("005930", _past(1), "10:00", 1100.0)  # 2일 < MIN 3일

    assert rebuild_baselines(conn) == 0
    assert BaselineRepository(conn).get("005930", "10:00") is None


def test_rebuild_excludes_today(conn):
    obs = ObservationsRepository(conn)
    for d in (4, 3, 2):
        obs.record("005930", _past(d), "10:00", 1000.0)
    obs.record("005930", date.today().isoformat(), "10:00", 99_999_999.0)  # 오늘 서지

    rebuild_baselines(conn)
    row = BaselineRepository(conn).get("005930", "10:00")
    assert row["avg_cum_volume"] == pytest.approx(1000.0)  # 오늘 값이 오염시키지 않음


def test_rebuild_lookback_uses_recent_days_only(conn):
    obs = ObservationsRepository(conn)
    obs.record("005930", _past(30), "10:00", 500_000.0)  # 오래된 관측
    for d in range(1, 21):  # 최근 20일
        obs.record("005930", _past(d), "10:00", 1000.0)

    rebuild_baselines(conn, lookback_days=20)
    row = BaselineRepository(conn).get("005930", "10:00")
    assert row["days"] == 20
    assert row["avg_cum_volume"] == pytest.approx(1000.0)  # 오래된 값 제외


def test_observation_upsert_keeps_latest(conn):
    obs = ObservationsRepository(conn)
    today = date.today().isoformat()
    obs.record("005930", today, "10:00", 100.0)
    obs.record("005930", today, "10:00", 200.0)  # 같은 슬롯 재관측 → 최신 값

    row = conn.execute(
        "SELECT cum_volume FROM intraday_observations WHERE symbol='005930'"
    ).fetchone()
    assert row["cum_volume"] == 200.0


def test_tracker_records_observations(conn):
    """트래커 사이클이 관측치를 남기는지 (mock 데모 재사용)."""
    from aim.delivery.router import NotificationRouter
    from aim.storage.repositories.watch import WatchlistRepository
    from aim.watch.provider import demo_scenario
    from aim.watch.tracker import WatchTracker

    quotes, disclosures, symbol = demo_scenario(BaselineRepository(conn))
    WatchlistRepository(conn).add(symbol, "삼성전자")

    class Sink:
        name = "sink"

        def send(self, t, b):
            return True

    tracker = WatchTracker(conn, quotes, disclosures, NotificationRouter({}, [Sink()]))
    tracker.run_once(datetime(2026, 7, 20, 10, 0))

    rows = conn.execute("SELECT * FROM intraday_observations WHERE symbol = ?", (symbol,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["time_slot"] == "10:00"
