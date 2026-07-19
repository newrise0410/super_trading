"""반성 루프 + 대시보드 데이터 함수 + 두뇌 지식 주입 검증."""

import json

import pytest

from aim.brain.reflect import evaluate_outcomes
from aim.storage import db
from aim.storage.repositories.decisions import DecisionsRepository
from aim.web.app import decisions_data, equity_data, report_detail, reports_list


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    yield c
    c.close()


def _seed_decision(conn, *, action="BUY", price=100.0, created="2026-07-01 10:00:00", confidence=0.72):
    decision_id = DecisionsRepository(conn).save(
        market="KR", symbol="005930", name="삼성전자", action=action,
        strategy="ai_debate_v1", confidence=confidence,
        data_snapshot={"price": price, "as_of": created[:10], "items": []},
    )
    conn.execute("UPDATE decisions SET created_at = ? WHERE decision_id = ?", (created, decision_id))
    conn.commit()
    return decision_id


# ── 반성 루프 ─────────────────────────────────────────────────

def test_outcome_evaluated_and_knowledge_recorded(conn):
    _seed_decision(conn, action="BUY", price=100.0)
    n = evaluate_outcomes(conn, price_after=lambda s, m, d: 110.0)
    assert n == 1

    row = conn.execute("SELECT * FROM decisions").fetchone()
    assert row["outcome_return_5d"] == pytest.approx(10.0)
    assert row["outcome_evaluated_at"] is not None

    fact = conn.execute(
        "SELECT * FROM stock_facts WHERE fact_type='outcome'"
    ).fetchone()
    assert "적중" in fact["content"] and "+10.0%" in fact["content"]
    assert fact["valid_until"] is None  # outcome은 무기한


def test_avoid_hit_when_price_falls(conn):
    _seed_decision(conn, action="AVOID", price=100.0)
    evaluate_outcomes(conn, price_after=lambda s, m, d: 90.0)
    fact = conn.execute("SELECT content FROM stock_facts WHERE fact_type='outcome'").fetchone()
    assert "적중" in fact["content"]


def test_recent_decision_not_due(conn):
    from datetime import datetime
    _seed_decision(conn, created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    assert evaluate_outcomes(conn, price_after=lambda s, m, d: 110.0) == 0


def test_missing_price_stays_pending(conn):
    _seed_decision(conn)
    assert evaluate_outcomes(conn, price_after=lambda s, m, d: None) == 0
    row = conn.execute("SELECT outcome_evaluated_at FROM decisions").fetchone()
    assert row["outcome_evaluated_at"] is None  # 다음 실행에서 재시도


# ── 두뇌 지식 주입 ────────────────────────────────────────────

def test_debate_injects_accumulated_knowledge(conn):
    from aim.brain.debate import analyze_stock
    from aim.evidence.models import EvidenceItem, StockEvidence
    from aim.knowledge import KnowledgeStore

    KnowledgeStore(conn).upsert_fact(
        market="KR", symbol="005930", fact_type="outcome", topic="o1",
        content="[AVOID] 과거 판단 → 5거래일 -8.8% — 적중",
    )
    evidence = StockEvidence(
        symbol="005930", name="삼성전자", market="KR", as_of="2026-07-19",
        price=255000.0, change_pct=-8.77,
        items=[EvidenceItem("tech.rsi14", "technical", "RSI(14)", 32.1)],
    )

    class FakeLLM:
        def __init__(self, reply):
            self.name, self.model, self.reply, self.calls = "f", "f1", reply, []

        def complete(self, system, user):
            self.calls.append(user)
            return self.reply

    quick = FakeLLM("논거")
    deep = FakeLLM(json.dumps({"action": "WATCH", "confidence": 50, "summary": "s",
                               "rationale": [], "risks": [], "horizon": "5d",
                               "entry": None, "target": None, "stop": None}))
    analyze_stock(conn, evidence, quick, deep)
    assert "축적된 종목 지식" in quick.calls[0]
    assert "-8.8% — 적중" in quick.calls[0]  # 과거 결과가 다음 판단의 입력이 됨


# ── 대시보드 데이터 함수 ──────────────────────────────────────

def test_equity_data_indexed_to_pct(conn):
    conn.execute(
        "INSERT INTO virtual_portfolios (strategy, market, initial_cash, cash)"
        " VALUES ('benchmark', 'KR', 100000000, 0)"
    )
    pf_id = conn.execute("SELECT id FROM virtual_portfolios").fetchone()["id"]
    conn.execute("INSERT INTO sim_equity VALUES (?, '2026-07-16', 100000000)", (pf_id,))
    conn.execute("INSERT INTO sim_equity VALUES (?, '2026-07-17', 103000000)", (pf_id,))
    conn.commit()

    data = equity_data(conn)
    assert len(data["series"]) == 1
    s = data["series"][0]
    assert s["label"] == "벤치마크(K200)"
    assert s["points"] == [["2026-07-16", 0.0], ["2026-07-17", 3.0]]


def test_decisions_and_reports_data(conn):
    _seed_decision(conn)
    from aim.storage.repositories.reports import ReportsRepository
    report_id = ReportsRepository(conn).save("kr_close", "KR", "# 본문", {})

    decisions = decisions_data(conn)
    assert decisions[0]["symbol"] == "005930"

    reports = reports_list(conn)
    assert reports[0]["report_id"] == report_id
    assert report_detail(conn, report_id)["master_md"] == "# 본문"
    assert report_detail(conn, "nope") is None
