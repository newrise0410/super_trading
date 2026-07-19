"""토론 파이프라인 — 판정 파싱·판단 기록·지식 축적·카드 렌더 (LLM은 fake)."""

import json

import pytest

from aim.brain.debate import STRATEGY, _parse_verdict, analyze_stock
from aim.evidence.models import EvidenceItem, StockEvidence
from aim.storage import db


class FakeLLM:
    def __init__(self, replies):
        self.name = "fake"
        self.model = "fake-1"
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.replies.pop(0)


VERDICT = {
    "action": "BUY", "confidence": 72,
    "summary": "외인 수급과 추세가 정배열 — 매수 우위",
    "entry": 71000, "target": 78000, "stop": 67500, "horizon": "20d",
    "rationale": [
        {"evidence_key": "flow.foreign_streak", "text": "외국인 5일 연속 순매수"},
        {"evidence_key": "tech.ma20", "text": "MA20 위 정배열"},
    ],
    "risks": [{"text": "RSI 과열 접근 시 되돌림 가능"}],
}


def _evidence():
    return StockEvidence(
        symbol="005930", name="삼성전자", market="KR", as_of="2026-07-18",
        price=71000.0, change_pct=2.9,
        items=[
            EvidenceItem("flow.foreign_streak", "flow", "외국인 연속 순매수", 5, "일", direction="bullish"),
            EvidenceItem("tech.ma20", "technical", "MA20 대비", 3.2, "%", direction="bullish"),
            EvidenceItem("tech.rsi14", "technical", "RSI(14)", 58.0),
        ],
    )


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    yield c
    c.close()


def test_analyze_full_flow(conn):
    quick = FakeLLM(["강세 논거 [flow.foreign_streak]", "약세 반박 [tech.rsi14]"])
    deep = FakeLLM([json.dumps(VERDICT, ensure_ascii=False)])

    result = analyze_stock(conn, _evidence(), quick, deep)

    assert result.action == "BUY"
    assert result.confidence == pytest.approx(0.72)
    # Bear는 Bull의 주장을 봤어야 한다
    assert "강세 논거" in quick.calls[1][1]
    # 판정자는 토론 전문을 봤어야 한다
    assert "강세 논거" in deep.calls[0][1] and "약세 반박" in deep.calls[0][1]

    # 판단 기록 검증 — 근거·토론로그·증거 스냅샷 동결
    row = conn.execute("SELECT * FROM decisions WHERE decision_id = ?", (result.decision_id,)).fetchone()
    assert row["action"] == "BUY" and row["strategy"] == STRATEGY
    rationale = json.loads(row["rationale_json"])
    assert rationale[0]["evidence_key"] == "flow.foreign_streak"
    debate = json.loads(row["debate_log_json"])
    assert [t["role"] for t in debate] == ["bull", "bear", "judge"]
    snapshot = json.loads(row["data_snapshot_json"])
    assert snapshot["symbol"] == "005930" and len(snapshot["items"]) == 3

    # 지식저장소 축적 — thesis + risk
    facts = {r["fact_type"] for r in conn.execute(
        "SELECT fact_type FROM stock_facts WHERE symbol='005930' AND superseded_by IS NULL"
    )}
    assert facts == {"thesis", "risk"}


def test_reanalysis_supersedes_thesis(conn):
    for verdict_action in ("BUY", "WATCH"):
        verdict = dict(VERDICT, action=verdict_action)
        analyze_stock(
            conn, _evidence(),
            FakeLLM(["b", "r"]), FakeLLM([json.dumps(verdict, ensure_ascii=False)]),
        )
    active = conn.execute(
        "SELECT content FROM stock_facts WHERE symbol='005930' AND fact_type='thesis'"
        " AND superseded_by IS NULL"
    ).fetchall()
    assert len(active) == 1
    assert "WATCH" in active[0]["content"]  # 최신 판단이 대체


def test_card_contains_core_elements(conn):
    result = analyze_stock(
        conn, _evidence(), FakeLLM(["b", "r"]), FakeLLM([json.dumps(VERDICT, ensure_ascii=False)])
    )
    card = result.card_md
    assert "삼성전자" in card and "005930" in card
    assert "확신도 72%" in card
    assert "① 외국인 5일 연속 순매수" in card
    assert "진입 71,000 / 목표 78,000 (+9.9%) / 손절 67,500 (-4.9%)" in card


def test_parse_verdict_handles_prose_and_fences():
    wrapped = f"판단 결과입니다:\n```json\n{json.dumps(VERDICT)}\n```\n이상입니다."
    assert _parse_verdict(wrapped)["action"] == "BUY"

    with pytest.raises(ValueError):
        _parse_verdict("JSON이 없는 응답")


def test_watch_action_without_prices(conn):
    verdict = dict(VERDICT, action="WATCH", entry=None, target=None, stop=None)
    result = analyze_stock(
        conn, _evidence(), FakeLLM(["b", "r"]), FakeLLM([json.dumps(verdict, ensure_ascii=False)])
    )
    assert result.action == "WATCH"
    assert "시나리오" not in result.card_md  # 가격 없으면 시나리오 줄 생략
