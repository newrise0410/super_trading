"""대가 패널 — 판정 파싱·합의·일별 캐시·페르소나 시뮬레이션 검증."""

import json

import pytest

from aim.panel.engine import run_panel, todays_verdicts
from aim.panel.personas import PERSONAS
from aim.storage import db


class PanelFakeLLM:
    """페르소나별로 다른 판정을 주는 LLM."""

    STANCES = ["BUY", "BUY", "HOLD", "AVOID", "AVOID", "AVOID"]

    def __init__(self):
        self.name, self.model, self.calls = "fake", "f1", []

    def complete(self, system, user):
        self.calls.append((system, user))
        idx = (len(self.calls) - 1) % 6
        return json.dumps({
            "stance": self.STANCES[idx], "confidence": 70 + idx,
            "thesis": f"관점 {idx}", "key_metric": "PER",
        })


class FakeSettings:
    kis_app_key = ""
    kis_app_secret = ""
    kis_env = "prod"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    from aim.evidence.models import EvidenceItem, StockEvidence

    monkeypatch.setattr(
        "aim.evidence.collector.collect_kr_evidence",
        lambda symbol, as_of=None: StockEvidence(
            symbol=symbol, name="삼성전자", market="KR", as_of="2026-07-19",
            price=255000.0, change_pct=0.0,
            items=[EvidenceItem("tech.rsi14", "technical", "RSI(14)", 32.1)],
        ),
    )
    yield c
    c.close()


def test_panel_verdicts_and_consensus(conn):
    quick = PanelFakeLLM()
    result = run_panel(conn, FakeSettings(), "005930", quick, run_date="2026-07-19")

    assert len(result["verdicts"]) == len(PERSONAS)
    assert result["verdicts"][0]["persona"] == "buffett"
    c = result["consensus"]
    assert c["counts"] == {"BUY": 2, "HOLD": 1, "AVOID": 3}
    assert c["majority"] == "AVOID" and c["agreement_pct"] == 50
    # 각 페르소나가 증거를 받았는지
    assert all("RSI(14)" in call[1] for call in quick.calls)


def test_panel_daily_cache(conn):
    quick = PanelFakeLLM()
    run_panel(conn, FakeSettings(), "005930", quick, run_date="2026-07-19")
    calls_after_first = len(quick.calls)

    cached = run_panel(conn, FakeSettings(), "005930", quick, run_date="2026-07-19")
    assert cached["cached"] is True
    assert len(quick.calls) == calls_after_first          # LLM 재호출 없음

    forced = run_panel(conn, FakeSettings(), "005930", quick, run_date="2026-07-19", force=True)
    assert forced["cached"] is False
    assert len(quick.calls) > calls_after_first


def test_persona_failure_isolated(conn):
    class FlakyLLM(PanelFakeLLM):
        def complete(self, system, user):
            self.calls.append((system, user))
            if len(self.calls) == 2:                       # 그레이엄만 파싱 불가
                return "JSON 아님"
            return super().complete(system, user)

    # FlakyLLM의 super() 호출이 calls를 중복 기록하므로 단순화
    class Flaky2(PanelFakeLLM):
        def complete(self, system, user):
            self.calls.append((system, user))
            if len(self.calls) == 2:
                return "JSON 아님"
            idx = (len(self.calls) - 1) % 6
            return json.dumps({"stance": "HOLD", "confidence": 50,
                               "thesis": f"t{idx}", "key_metric": "m"})

    result = run_panel(conn, FakeSettings(), "005930", Flaky2(), run_date="2026-07-19")
    assert len(result["verdicts"]) == len(PERSONAS) - 1    # 1명 탈락, 나머지 진행


def test_verdict_validation_and_forced_abstain(conn):
    """검증: 잘못된 stance→HOLD, confidence 클램프, missing 있으면 BUY→HOLD·conf≤40."""

    class BadLLM(PanelFakeLLM):
        def complete(self, system, user):
            self.calls.append((system, user))
            idx = len(self.calls) - 1
            if idx == 0:   # 데이터 없는데 BUY 90 → 강제 기권 대상
                return json.dumps({"stance": "BUY", "confidence": 90, "thesis": "t",
                                   "key_metric": "m", "missing": ["EPS 성장률"]})
            if idx == 1:   # 엉뚱한 stance
                return json.dumps({"stance": "STRONG_BUY", "confidence": 300,
                                   "thesis": "t", "key_metric": "m"})
            return json.dumps({"stance": "HOLD", "confidence": 50, "thesis": "t",
                               "key_metric": "m", "missing": []})

    result = run_panel(conn, FakeSettings(), "005930", BadLLM(), run_date="2026-07-19")
    v0, v1 = result["verdicts"][0], result["verdicts"][1]
    assert v0["stance"] == "HOLD" and v0["confidence"] <= 40      # 강제 기권
    assert v0["missing"] == ["EPS 성장률"]
    assert v1["stance"] == "HOLD" and v1["confidence"] == 100      # enum·범위 정규화


# ── 페르소나 시뮬레이션 ───────────────────────────────────────

PRICES = {"005930": (255000.0, -8.77), "069500": (109000.0, -6.63)}


def _lookup(symbol):
    return PRICES.get(symbol)


def _seed_panel(conn, date, stance, confidence=80):
    verdicts = [{"persona": slug, "display": name, "stance": stance,
                 "confidence": confidence, "thesis": "", "key_metric": ""}
                for slug, name, _p in PERSONAS]
    conn.execute(
        "INSERT OR REPLACE INTO panel_runs (symbol, run_date, name, verdicts_json, consensus_json)"
        " VALUES ('005930', ?, '삼성전자', ?, '{}')",
        (date, json.dumps(verdicts, ensure_ascii=False)),
    )
    conn.commit()


def test_persona_sim_buys_on_buy_verdict(conn):
    from aim.data.models import MarketSnapshot
    from aim.simulation.engine import run_close_cycle

    _seed_panel(conn, "2026-07-20", "BUY", 80)
    snap = MarketSnapshot(market="KR", date="2026-07-20", session="close")
    _values, trades = run_close_cycle(conn, snap, _lookup, "2026-07-20")

    buffett_trades = [t for t in trades if t["strategy"] == "p_buffett"]
    assert len(buffett_trades) == 1 and buffett_trades[0]["side"] == "BUY"

    # 다음 날 AVOID → 청산
    _seed_panel(conn, "2026-07-21", "AVOID")
    _values, trades2 = run_close_cycle(conn, snap, _lookup, "2026-07-21")
    assert any(t["strategy"] == "p_buffett" and t["side"] == "SELL" for t in trades2)


def test_persona_sim_skips_low_confidence(conn):
    from aim.data.models import MarketSnapshot
    from aim.simulation.engine import run_close_cycle

    _seed_panel(conn, "2026-07-20", "BUY", confidence=40)   # 60 미만
    snap = MarketSnapshot(market="KR", date="2026-07-20", session="close")
    _values, trades = run_close_cycle(conn, snap, _lookup, "2026-07-20")
    assert not any(t["strategy"].startswith("p_") for t in trades)


def test_todays_verdicts_shape(conn):
    _seed_panel(conn, "2026-07-20", "BUY")
    v = todays_verdicts(conn, "2026-07-20")
    assert v["005930"]["buffett"]["stance"] == "BUY"
