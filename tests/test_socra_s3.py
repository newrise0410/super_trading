"""S3 살아있는 결정 카드 — 스냅샷 동결·diff·기준선·쿨다운·재질문 세션 검증."""

import json

import pytest

from aim.socra.concepts import seed_concepts
from aim.socra.engine import STAGES, SocraEngine
from aim.socra.watchcards import diff_evidence, review_cards
from aim.storage import db

# 조작 가능한 증거 상태 (monkeypatch된 collector가 읽음)
STATE = {
    "price": 255000.0,
    "items": [
        {"key": "flow.foreign_streak", "category": "flow", "label": "외국인 연속 순매수",
         "value": 5, "unit": "일", "direction": "bullish", "detail": ""},
        {"key": "tech.ma20", "category": "technical", "label": "MA20 대비",
         "value": 3.2, "unit": "%", "direction": "bullish", "detail": ""},
    ],
}


class FakeLLM:
    def __init__(self, replies=None):
        self.name, self.model = "fake", "f1"
        self.replies = list(replies or [])
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.replies.pop(0) if self.replies else "질문입니다? [[NEXT]]"


class FakeSettings:
    kis_app_key = ""
    kis_app_secret = ""
    kis_env = "prod"


class FakeRouter:
    def __init__(self):
        self.sent = []
        self.configured_routes = ["cards"]

    def send(self, route, title, body):
        self.sent.append((route, title, body))
        return True


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    seed_concepts(c)
    from aim.evidence.models import EvidenceItem, StockEvidence

    def fake_collect(symbol, as_of=None):
        return StockEvidence(
            symbol=symbol, name="삼성전자", market="KR", as_of="2026-07-19",
            price=STATE["price"], change_pct=0.0,
            items=[EvidenceItem(i["key"], i["category"], i["label"], i["value"],
                                i["unit"], i["detail"], i["direction"]) for i in STATE["items"]],
        )

    monkeypatch.setattr("aim.evidence.collector.collect_kr_evidence", fake_collect)
    yield c
    c.close()


CARD_JSON = json.dumps({
    "thesis": "외인 수급 믿고 보유", "target_price": 300000, "target_reason": "전고점",
    "stop_price": 230000, "stop_reason": "저점 이탈",
    "recheck_conditions": ["외인 순매도 전환"], "confidence_self": 60, "gaps": [],
}, ensure_ascii=False)


def _make_card(conn, quick=None, deep=None) -> str:
    engine = SocraEngine(conn, FakeSettings(), quick or FakeLLM(), deep or FakeLLM([CARD_JSON]))
    sid = engine.start_session("삼성전자")["session_id"]
    for i in range(len(STAGES)):
        engine.handle_message(sid, f"답 {i}")
    result = engine.handle_message(sid, "확정")
    return result["card_id"]


# ── 스냅샷 동결 ───────────────────────────────────────────────

def test_card_freezes_structured_snapshot(conn):
    _make_card(conn)
    card = conn.execute("SELECT * FROM decision_cards").fetchone()
    snap = json.loads(card["evidence_snapshot_json"])
    assert snap["price"] == 255000.0
    keys = {i["key"] for i in snap["items"]}
    assert "flow.foreign_streak" in keys and "tech.ma20" in keys
    assert snap["items"][0]["direction"] == "bullish"


# ── diff 룰 ──────────────────────────────────────────────────

def test_diff_detects_direction_flip_only():
    old = [{"key": "a", "label": "외인", "value": 5, "unit": "일", "direction": "bullish"},
           {"key": "b", "label": "MA20", "value": 3.2, "unit": "%", "direction": "bullish"}]
    new = [{"key": "a", "label": "외인", "value": 3, "unit": "일", "direction": "bearish"},
           {"key": "b", "label": "MA20", "value": 1.1, "unit": "%", "direction": "bullish"}]
    alerts = diff_evidence(old, new)
    assert len(alerts) == 1
    assert alerts[0][0] == "flip:a" and "긍정→부정" in alerts[0][1]


# ── 리뷰: 기준선·반전·쿨다운·알림 ─────────────────────────────

def test_review_fires_stop_and_flip_with_cooldown(conn):
    card_id = _make_card(conn)

    STATE["price"] = 225000.0                      # 손절선(230,000) 이탈
    STATE["items"][0] = dict(STATE["items"][0], value=3, direction="bearish")  # 외인 반전
    try:
        router = FakeRouter()
        results = review_cards(conn, FakeSettings(), quick=None, router=router)
        assert len(results) == 1
        alerts = results[0]["alerts"]
        assert any("손절선 도달" in a for a in alerts)
        assert any("긍정→부정" in a for a in alerts)

        # 알림 발송 + 웹 링크 포함
        _route, _title, body = router.sent[0]
        assert card_id in body and "?card=" in body

        # 쿨다운 — 같은 날 재실행 시 무음
        assert review_cards(conn, FakeSettings(), quick=None, router=router) == []
    finally:
        STATE["price"] = 255000.0
        STATE["items"][0] = dict(STATE["items"][0], value=5, direction="bullish")


def test_review_recheck_condition_via_llm(conn):
    _make_card(conn)
    quick = FakeLLM(['{"triggered": [0]}'])
    results = review_cards(conn, FakeSettings(), quick=quick, router=None)
    assert any("재검토 조건 발동" in a and "외인 순매도 전환" in a for a in results[0]["alerts"])
    # LLM에 조건과 최신 증거가 전달됐는지
    assert "외인 순매도 전환" in quick.calls[0][1]


def test_review_quiet_when_nothing_changed(conn):
    _make_card(conn)
    assert review_cards(conn, FakeSettings(), quick=None, router=None) == []


# ── 재질문 세션 → 카드 v2 ─────────────────────────────────────

def test_requestion_flow_creates_card_v2(conn):
    card_id = _make_card(conn)
    conn.execute(
        "INSERT INTO card_alerts (card_id, kind, message) VALUES (?, 'flip:x', '외인 반전')",
        (card_id,),
    )
    conn.commit()

    card2_json = json.dumps({**json.loads(CARD_JSON),
                             "thesis": "수급 꺾여서 목표 하향", "target_price": 270000},
                            ensure_ascii=False)
    quick = FakeLLM()  # 기본 응답에 [[NEXT]] 포함 → 재점검 1턴 후 카드
    engine = SocraEngine(conn, FakeSettings(), quick, FakeLLM([card2_json]))

    r = engine.start_requestion(card_id)
    assert r["stage"] == "recheck"
    # 오프닝 프롬프트에 기존 카드·알림·최신 증거가 배경으로 들어감
    system = quick.calls[0][0]
    assert "외인 수급 믿고 보유" in system and "외인 반전" in system and "300,000" not in system

    r2 = engine.handle_message(r["session_id"], "수급이 꺾였으니 목표를 낮출게요")
    assert r2["stage"] == "card"
    done = engine.handle_message(r["session_id"], "확정")
    assert done["stage"] == "done"

    cards = conn.execute(
        "SELECT version, status, target_price FROM decision_cards ORDER BY id"
    ).fetchall()
    assert [(c["version"], c["status"]) for c in cards] == [(1, "superseded"), (2, "active")]
    assert cards[1]["target_price"] == 270000
