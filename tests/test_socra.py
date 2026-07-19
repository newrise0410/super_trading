"""소크라 엔진 — 상태 머신·가드레일 흐름·카드 저장·범례 검증 (LLM·증거는 fake)."""

import json

import pytest

from aim.socra.concepts import detect_terms, seed_concepts
from aim.socra.engine import STAGES, SocraEngine, resolve_symbol
from aim.storage import db


class FakeLLM:
    def __init__(self, replies=None):
        self.name, self.model = "fake", "f1"
        self.replies = list(replies or [])
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.replies.pop(0) if self.replies else "질문입니다?"


class FakeSettings:
    kis_app_key = ""
    kis_app_secret = ""
    kis_env = "prod"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    seed_concepts(c)
    # 증거 수집을 결정론적으로
    from aim.evidence.models import EvidenceItem, StockEvidence

    monkeypatch.setattr(
        "aim.evidence.collector.collect_kr_evidence",
        lambda symbol, as_of=None: StockEvidence(
            symbol=symbol, name="삼성전자", market="KR", as_of="2026-07-19",
            price=255000.0, change_pct=-8.77,
            items=[EvidenceItem("tech.rsi14", "technical", "RSI(14)", 32.1)],
        ),
    )
    yield c
    c.close()


def _engine(conn, quick=None, deep=None):
    return SocraEngine(conn, FakeSettings(), quick or FakeLLM(), deep or FakeLLM())


CARD_JSON = json.dumps({
    "thesis": "HBM 성장 믿고 장기 보유", "target_price": 300000,
    "target_reason": "전고점 근처", "stop_price": 230000, "stop_reason": "최근 저점 아래",
    "recheck_conditions": ["외인 순매도 전환"], "confidence_self": 60, "gaps": [],
}, ensure_ascii=False)


# ── 심볼 해석 ─────────────────────────────────────────────────

def test_resolve_symbol():
    assert resolve_symbol("삼성전자 살까 말까?")[0] == "005930"
    assert resolve_symbol("005930")[0] == "005930"
    assert resolve_symbol("SK하이닉스 어때")[0] == "000660"
    assert resolve_symbol("듣도보도못한종목") is None


# ── 세션 흐름 ─────────────────────────────────────────────────

def test_start_session_creates_evidence_watchlist_and_opening(conn):
    result = _engine(conn).start_session("삼성전자 살까?")
    assert result["stage"] == "business"
    assert result["symbol"] == "005930"

    session = conn.execute("SELECT * FROM socra_sessions").fetchone()
    assert "RSI(14)" in session["evidence_md"]          # 증거 동봉
    wl = conn.execute("SELECT symbol FROM watchlist").fetchone()
    assert wl["symbol"] == "005930"                     # 자동 관심종목
    turns = conn.execute("SELECT role FROM socra_turns").fetchall()
    assert [t["role"] for t in turns] == ["bot"]


class NextLLM(FakeLLM):
    """항상 [[NEXT]] 신호를 주는 LLM — 여정 테스트용."""

    def complete(self, system, user):
        self.calls.append((system, user))
        return "좋은 답이에요! 다음 질문입니다? [[NEXT]]"


def test_stage_advance_by_llm_marker(conn):
    quick = FakeLLM(["오프닝?", "조금 더 들려주세요", "충분해요! [[NEXT]]"])
    engine = _engine(conn, quick)
    sid = engine.start_session("삼성전자")["session_id"]

    r1 = engine.handle_message(sid, "반도체 만드는 회사요")
    assert r1["stage"] == "business"                    # 마커 없음 — 유지
    r2 = engine.handle_message(sid, "메모리가 주력이에요")
    assert r2["stage"] == "valuation"                   # [[NEXT]] — 전진
    assert "[[NEXT]]" not in r2["reply"]                # 내부 신호는 비노출


def test_stage_forced_advance_at_max_turns(conn):
    engine = _engine(conn, FakeLLM())                   # 기본 응답 — 마커 없음
    sid = engine.start_session("삼성전자")["session_id"]
    stages = [engine.handle_message(sid, f"답 {i}")["stage"] for i in range(4)]
    assert stages == ["business"] * 3 + ["valuation"]   # 4답째 강제 전진 (늘어짐 방지)


def test_full_journey_reaches_card_and_saves(conn):
    quick = NextLLM()
    deep = FakeLLM([CARD_JSON])
    engine = _engine(conn, quick, deep)
    sid = engine.start_session("삼성전자")["session_id"]

    result = None
    for i in range(len(STAGES)):                        # 매 답마다 [[NEXT]] → 4답이면 카드
        result = engine.handle_message(sid, f"답변 {i}")
    assert result["stage"] == "card"
    assert result["card_draft"]["target_price"] == 300000
    assert "확정" in result["reply"]

    done = engine.handle_message(sid, "확정")
    assert done["stage"] == "done"
    card = conn.execute("SELECT * FROM decision_cards").fetchone()
    assert card["thesis"].startswith("HBM")
    assert card["version"] == 1 and card["status"] == "active"
    snap = json.loads(card["evidence_snapshot_json"])                              # §4.5 동결
    assert any(i["key"] == "tech.rsi14" for i in snap["items"])                    # 구조화 스냅샷
    assert snap["price"] == 255000.0


def test_resave_supersedes_previous_card(conn):
    for _ in range(2):
        quick, deep = NextLLM(), FakeLLM([CARD_JSON])
        engine = _engine(conn, quick, deep)
        sid = engine.start_session("삼성전자")["session_id"]
        for i in range(len(STAGES)):
            engine.handle_message(sid, f"답 {i}")
        engine.handle_message(sid, "확정")

    cards = conn.execute("SELECT version, status FROM decision_cards ORDER BY id").fetchall()
    assert [(c["version"], c["status"]) for c in cards] == [(1, "superseded"), (2, "active")]


def test_turn_prompt_contains_guardrails_and_evidence(conn):
    quick = FakeLLM()
    engine = _engine(conn, quick)
    sid = engine.start_session("삼성전자")["session_id"]
    engine.handle_message(sid, "그래서 사라는 거예요?")

    system = quick.calls[-1][0]
    assert "판단을 대신하는 말을 절대 하지 않는다" in system   # 가드레일
    assert "RSI(14)" in system                                # 증거
    assert "① 사업 이해" in system                            # 단계 목표
    assert "반증 조건" in system                              # 인사이트 검증 규칙
    assert "배경지식으로 판정하지 마라" in system              # 환각 검증 금지


def test_evidence_keys_stripped_from_replies(conn):
    """내부 증거 키([tech.x])가 사용자 응답에 누출되지 않는다 (서버측 필터)."""
    quick = FakeLLM([
        "환영해요 [tech.rsi14] 질문입니다?",              # 오프닝
        "-11.53% 떨어졌어요 [tech.ret5d][tech.ret20d]. 왜일까요?",  # 턴
    ])
    engine = _engine(conn, quick)
    opening = engine.start_session("삼성전자")
    assert "[tech" not in opening["reply"]

    result = engine.handle_message(opening["session_id"], "몰라요")
    assert "[tech" not in result["reply"]
    assert "-11.53%" in result["reply"]                    # 수치는 보존


# ── 범례 ─────────────────────────────────────────────────────

def test_legend_detects_terms_in_order(conn):
    legend = detect_terms(conn, "시총이 크고 PER은 12배예요. 외국인 순매수도 이어지네요.")
    terms = [item["term"] for item in legend]
    assert terms == ["시가총액", "PER", "수급"]      # 등장 순서
    assert "1년 이익" in legend[1]["short_def"]


def test_legend_caps_at_five(conn):
    text = "PER PBR 시총 거래량 손절 익절 배당 공시"
    assert len(detect_terms(conn, text)) == 5


# ── 지식 모델 (S2) ────────────────────────────────────────────

def test_legend_omits_demonstrated_and_records_exposure(conn):
    from aim.socra.mastery import MasteryModel

    r = _engine(conn, FakeLLM(["PER과 시총을 볼게요. 어떠세요?"])).start_session("삼성전자")
    assert {l["slug"] for l in r["legend"]} == {"per", "market_cap"}
    row = conn.execute("SELECT level, exposures FROM concept_mastery WHERE slug='per'").fetchone()
    assert row["level"] == 1 and row["exposures"] == 1      # 노출 기록

    MasteryModel(conn).record_demonstrated(["per"])
    r2 = _engine(conn, FakeLLM(["다시 PER과 시총 얘기예요."])).start_session("005930")
    assert {l["slug"] for l in r2["legend"]} == {"market_cap"}  # 이해한 PER은 범례 생략


def test_asked_detection_marks_unskilled(conn):
    engine = _engine(conn, FakeLLM())
    sid = engine.start_session("삼성전자")["session_id"]
    engine.handle_message(sid, "PER이 뭐예요?")
    row = conn.execute("SELECT level FROM concept_mastery WHERE slug='per'").fetchone()
    assert row["level"] == 2                                # 질문 = 미숙련 신호


def test_mastery_summary_injected_into_prompt(conn):
    from aim.socra.mastery import MasteryModel

    MasteryModel(conn).record_demonstrated(["per"])
    MasteryModel(conn).record_asked("flow")
    quick = FakeLLM()
    engine = _engine(conn, quick)
    sid = engine.start_session("삼성전자")["session_id"]
    engine.handle_message(sid, "네")
    system = quick.calls[-1][0]
    assert "이해한 개념" in system and "PER" in system
    assert "미숙련 개념" in system and "수급" in system


def test_card_synth_updates_mastery(conn):
    card = json.loads(CARD_JSON)
    card["concepts_understood"] = ["per", "stop_loss"]
    card["concepts_confused"] = ["flow"]
    engine = _engine(conn, NextLLM(), FakeLLM([json.dumps(card, ensure_ascii=False)]))
    sid = engine.start_session("삼성전자")["session_id"]
    for i in range(len(STAGES)):
        engine.handle_message(sid, f"답 {i}")

    levels = {r["slug"]: r["level"] for r in conn.execute("SELECT slug, level FROM concept_mastery")}
    assert levels["per"] == 3 and levels["stop_loss"] == 3
    assert levels["flow"] == 2


# ── 종목 검색 (S2) ────────────────────────────────────────────

def _mst_line(code, name, tail_len):
    head = code.ljust(9) + "KR700000000X".ljust(12) + name
    return head + "0" * tail_len


def test_parse_mst_filters_and_extracts():
    from aim.socra.symbols import parse_mst

    lines = [
        _mst_line("005930", "삼성전자", 228),
        _mst_line("0001B0", "이상한신형코드", 228),   # 6자리 숫자 아님 → 제외
        _mst_line("035420", "NAVER", 228),
    ]
    rows = parse_mst("\n".join(lines).encode("cp949"), 228)
    assert rows == [("005930", "삼성전자"), ("035420", "NAVER")]


def test_sync_and_search_symbols(conn):
    import io
    import zipfile

    from aim.socra.symbols import search_symbol, sync_symbols

    def make_zip(inner, text, tail):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(inner, text.encode("cp949"))
        return buf.getvalue()

    def fake_fetch(url):
        if "kospi" in url:
            return make_zip("kospi_code.mst", _mst_line("005930", "삼성전자", 228), 228)
        return make_zip("kosdaq_code.mst", _mst_line("068270", "셀트리온", 222), 222)

    assert sync_symbols(conn, fetch=fake_fetch) == 2
    assert search_symbol(conn, "삼성전자") == ("005930", "삼성전자")
    assert search_symbol(conn, "셀트리온 살까 말까?") == ("068270", "셀트리온")
    assert search_symbol(conn, "없는종목") is None

    # resolve_symbol이 DB를 우선 사용
    from aim.socra.engine import resolve_symbol

    assert resolve_symbol("셀트리온 어때?", conn) == ("068270", "셀트리온")
