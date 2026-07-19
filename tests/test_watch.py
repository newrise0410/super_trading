"""watch 모듈 — 시그널 룰·쿨다운·COMBO·트래커 end-to-end 검증."""

from datetime import datetime

import pytest

from aim.delivery.router import NotificationRouter
from aim.storage import db
from aim.storage.repositories.watch import (
    BaselineRepository,
    SignalsRepository,
    WatchlistRepository,
)
from aim.watch.baseline import slot_of, zscore
from aim.watch.cooldown import Cooldown
from aim.watch.models import Disclosure, IntradayQuote
from aim.watch.provider import demo_scenario
from aim.watch.signals import (
    classify_disclosure,
    disclosure_signal,
    price_move_signal,
    volume_surge_signal,
)
from aim.watch.tracker import WatchTracker


class ListNotifier:
    name = "list"

    def __init__(self):
        self.sent = []

    def send(self, title, body_md):
        self.sent.append((title, body_md))
        return True


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    yield c
    c.close()


def _quote(symbol="005930", price=70000.0, cum_volume=5_000_000.0, at="2026-07-20 10:00:00", change_pct=0.5):
    return IntradayQuote(symbol, "삼성전자", price, change_pct, cum_volume, 3500.0, at)


# ── 룰 단위 ────────────────────────────────────────────────────

def test_slot_of_floors_to_5min():
    assert slot_of(datetime(2026, 7, 20, 10, 4)) == "10:00"
    assert slot_of(datetime(2026, 7, 20, 10, 5)) == "10:05"


def test_zscore_std_floor_prevents_blowup():
    assert zscore(1_000_000, avg=1_000_000, std=0.0) == 0.0


def test_volume_surge_threshold():
    assert volume_surge_signal(_quote(cum_volume=5_500_000), avg=5_000_000, std=500_000) is None  # z=1
    sig = volume_surge_signal(_quote(cum_volume=9_000_000), avg=5_000_000, std=500_000)  # z=8
    assert sig is not None and sig.kind == "VOLUME_SURGE" and sig.severity == "critical"


def test_price_move_both_directions():
    assert price_move_signal(_quote(price=71_000), base_price=70_000, window_minutes=5) is None  # +1.4%
    up = price_move_signal(_quote(price=72_500), base_price=70_000, window_minutes=5)
    assert up is not None and "급등" in up.message
    down = price_move_signal(_quote(price=67_500), base_price=70_000, window_minutes=5)
    assert down is not None and "급락" in down.message


def test_classify_disclosure():
    assert classify_disclosure("단일판매ㆍ공급계약체결") == "supply_contract"
    assert classify_disclosure("유상증자결정") == "rights_issue"
    assert classify_disclosure("관리종목 지정") == "delisting_risk"
    assert classify_disclosure("기타경영사항") == "other"


def test_disclosure_severity_mapping():
    critical = disclosure_signal(Disclosure("005930", "삼성전자", "상장폐지 사유 발생", "2026-07-20 10:00"))
    assert critical.severity == "critical"


# ── 쿨다운 ────────────────────────────────────────────────────

def test_cooldown_suppresses_within_window(conn):
    repo = SignalsRepository(conn)
    cd = Cooldown(repo, minutes=30)
    now = datetime(2026, 7, 20, 10, 0)
    sig = volume_surge_signal(_quote(cum_volume=9_000_000), avg=5_000_000, std=500_000)

    assert cd.allow("005930", "VOLUME_SURGE", now)
    repo.save(sig, "2026-07-20 10:00:00", delivered=True)
    assert not cd.allow("005930", "VOLUME_SURGE", datetime(2026, 7, 20, 10, 20))  # 20분 후 억제
    assert cd.allow("005930", "VOLUME_SURGE", datetime(2026, 7, 20, 10, 31))      # 31분 후 허용


# ── 트래커 end-to-end (mock 데모 시나리오) ─────────────────────

def test_tracker_demo_scenario_fires_combo(conn):
    quotes, disclosures, symbol = demo_scenario(BaselineRepository(conn))
    WatchlistRepository(conn).add(symbol, "삼성전자")
    notifier = ListNotifier()
    tracker = WatchTracker(conn, quotes, disclosures, NotificationRouter({}, [notifier]))

    # 10:00 — 평온: 시그널 없음
    fired1 = tracker.run_once(datetime(2026, 7, 20, 10, 0))
    assert fired1 == []

    # 10:05 — 서지 + 공시 + 급등 → COMBO 포함
    fired2 = tracker.run_once(datetime(2026, 7, 20, 10, 5))
    kinds = {s.kind for s in fired2}
    assert "VOLUME_SURGE" in kinds
    assert "DISCLOSURE" in kinds
    assert "PRICE_MOVE" in kinds
    assert "COMBO" in kinds
    assert len(notifier.sent) == len(fired2)

    # 시그널이 DB에 저장되고, 공시/COMBO는 knowledge에 catalyst 팩트로 기록됨
    saved = conn.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
    assert saved == len(fired2)
    facts = conn.execute(
        "SELECT fact_type FROM stock_facts WHERE symbol = ?", (symbol,)
    ).fetchall()
    assert {r["fact_type"] for r in facts} == {"catalyst"}
    assert len(facts) == 2  # DISCLOSURE + COMBO


def test_tracker_empty_watchlist_noop(conn):
    quotes, disclosures, _ = demo_scenario(BaselineRepository(conn))
    tracker = WatchTracker(conn, quotes, disclosures, NotificationRouter({}, [ListNotifier()]))
    assert tracker.run_once(datetime(2026, 7, 20, 10, 0)) == []
