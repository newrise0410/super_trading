"""/why 렌더 + US 브리핑 렌더 + 봇 why 파서 검증."""

import pytest

from aim.brain.why import render_why
from aim.chat.discord_bot import _parse_why
from aim.reports.us import build_us_close_briefing
from aim.storage import db
from aim.storage.repositories.decisions import DecisionsRepository


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    yield c
    c.close()


def test_render_why_full(conn):
    DecisionsRepository(conn).save(
        market="KR", symbol="005930", name="삼성전자", action="AVOID",
        strategy="ai_debate_v1", confidence=0.86, horizon="20d",
        rationale=[{"evidence_key": "tech.ma20", "text": "MA20 대비 -16.8%"}],
        risks=[{"text": "기술적 반등 가능성"}],
        debate_log=[
            {"role": "bull", "text": "강세 논거 " * 60},  # 300자 초과 → 잘림
            {"role": "bear", "text": "약세 논거"},
        ],
        data_snapshot={"as_of": "2026-07-18", "items": [1, 2, 3]},
    )
    md = render_why(conn, "005930")
    assert "AVOID" in md and "확신도 86%" in md
    assert "`tech.ma20`" in md
    assert "기술적 반등" in md
    assert "🐂 Bull" in md and "…" in md      # 잘림 표시
    assert "증거 3개 동결됨 (2026-07-18 기준)" in md


def test_render_why_no_record(conn):
    assert "판단 기록이 없습니다" in render_why(conn, "999999")


def test_parse_why_patterns():
    assert _parse_why("/why 005930") == "005930"
    assert _parse_why("why aapl") == "AAPL"
    assert _parse_why("왜 005930") == "005930"
    assert _parse_why("왜 올랐어?") is None
    assert _parse_why("일반 질문") is None


def test_us_briefing_render():
    md = build_us_close_briefing(
        "2026-07-18",
        [("S&P500", 7100.25, -0.8), ("NASDAQ", 24500.5, -1.2)],
        1487.0,
        "## 💼 내 포트폴리오\n- 애플 ...",
    )
    assert "미국장 마감 브리핑" in md
    assert "S&P500" in md and "-0.80%" in md
    assert "USD/KRW** 1,487.0" in md
    assert "내 포트폴리오" in md
    assert "투자 자문이 아닙니다" in md


def test_us_briefing_handles_empty_indices():
    md = build_us_close_briefing("2026-07-18", [], None, "")
    assert "지수 조회 실패" in md
