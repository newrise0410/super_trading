"""KnowledgeStore — 대체(supersede)·시효(TTL)·검색 동작 검증."""

from datetime import date, timedelta

import pytest

from aim.knowledge import KnowledgeStore
from aim.storage import db


@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.migrate(conn)
    yield KnowledgeStore(conn)
    conn.close()


def test_upsert_supersedes_same_topic(store):
    old_id = store.upsert_fact(
        market="KR", symbol="005930", fact_type="thesis", topic="hbm",
        content="HBM 수주 모멘텀으로 상승 논지", as_of="2026-07-01",
    )
    new_id = store.upsert_fact(
        market="KR", symbol="005930", fact_type="thesis", topic="hbm",
        content="HBM 공급 과잉 우려로 논지 약화", as_of="2026-07-18",
    )
    active = store.get_context("005930")
    ids = [r["fact_id"] for r in active]
    assert new_id in ids
    assert old_id not in ids  # 이전 팩트는 대체됨

    # 이력은 보존 (include된 전체 행에서 superseded_by로 추적 가능)
    row = store.conn.execute(
        "SELECT superseded_by FROM stock_facts WHERE fact_id = ?", (old_id,)
    ).fetchone()
    assert row["superseded_by"] == new_id


def test_different_topics_coexist(store):
    store.upsert_fact(market="KR", symbol="005930", fact_type="risk", topic="fx",
                      content="환율 리스크")
    store.upsert_fact(market="KR", symbol="005930", fact_type="risk", topic="china",
                      content="중국 수요 리스크")
    assert len(store.get_context("005930")) == 2


def test_stale_facts_excluded_by_default(store):
    old_date = (date.today() - timedelta(days=30)).isoformat()  # flow TTL=3일 → 만료
    store.upsert_fact(market="KR", symbol="005930", fact_type="flow", topic="",
                      content="외인 순매수 중", as_of=old_date)
    assert store.get_context("005930") == []
    stale = store.get_context("005930", include_stale=True)
    assert len(stale) == 1


def test_outcome_never_expires(store):
    old_date = (date.today() - timedelta(days=400)).isoformat()
    store.upsert_fact(market="KR", symbol="005930", fact_type="outcome", topic="d1",
                      content="2025-06 BUY 판단 → 5일 +4.2% 적중", as_of=old_date)
    assert len(store.get_context("005930")) == 1


def test_fts_search(store):
    store.upsert_fact(market="KR", symbol="005930", fact_type="business", topic="",
                      content="HBM 매출 비중 확대와 파운드리 수주")
    store.upsert_fact(market="KR", symbol="000660", fact_type="business", topic="",
                      content="HBM 시장 점유율 1위")
    hits = store.search("HBM")
    assert len(hits) == 2
    hits_samsung = store.search("HBM", symbol="005930")
    assert len(hits_samsung) == 1


def test_unknown_fact_type_rejected(store):
    with pytest.raises(ValueError):
        store.upsert_fact(market="KR", symbol="005930", fact_type="gossip",
                          content="루머")


def test_render_context_shows_freshness(store):
    store.upsert_fact(market="KR", symbol="005930", fact_type="thesis", topic="",
                      content="상승 논지", as_of="2026-07-18")
    text = KnowledgeStore.render_context(store.get_context("005930"))
    assert "2026-07-18 기준" in text
    assert "[thesis]" in text
