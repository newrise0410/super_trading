"""장전 브리핑 — 렌더·공시 필터 검증."""

from aim.reports.open import build_kr_open_briefing, build_us_open_briefing
from aim.watch.dart import fetch_disclosures_for
from aim.watch.models import Disclosure


def _disc(symbol="005930", title="단일판매ㆍ공급계약체결"):
    return Disclosure(symbol=symbol, corp_name="삼성전자", title=title, filed_at="2026-07-20")


def test_kr_open_full_render():
    md = build_kr_open_briefing(
        "2026-07-20",
        us_indices=[("S&P500", 7457.69, -1.01), ("NASDAQ", 25520.24, -1.40)],
        usdkrw=1487.5,
        disclosures=[_disc()],
        recent_signals=[{"fired_at": "2026-07-20 09:12:00", "symbol": "005930",
                         "kind": "DISCLOSURE", "message": "공시 발생"}],
        watch_names=["삼성전자", "SK하이닉스"],
        personal_md="## 💼 내 포트폴리오\n- ...",
    )
    assert "장전 브리핑" in md
    assert "간밤 미국 증시" in md and "S&P500" in md and "-1.01%" in md
    assert "새 공시" in md and "[공급계약·수주]" in md      # 카테고리 자동 분류
    assert "최근 24시간 시그널" in md
    assert "삼성전자 · SK하이닉스" in md
    assert "내 포트폴리오" in md and "투자 자문이 아닙니다" in md


def test_kr_open_omits_empty_sections():
    md = build_kr_open_briefing("2026-07-20", [], None, [], [], [], "")
    assert "새 공시" not in md and "시그널" not in md and "관심 종목" not in md
    assert "(조회 실패)" in md  # 지수 실패 표시


def test_us_open_render():
    md = build_us_open_briefing(
        "2026-07-20",
        futures=[("S&P500 선물", 7460.0, 0.3)],
        kr_summary=[("KOSPI", 6820.6, -6.37)],
        usdkrw=1487.0,
    )
    assert "지수 선물" in md and "S&P500 선물" in md
    assert "오늘 한국장 마감" in md and "KOSPI" in md


def test_fetch_disclosures_for_filters_symbols():
    def fake(params):
        return {"status": "000", "list": [
            {"stock_code": "005930", "corp_name": "삼성전자", "report_nm": "수주공시",
             "rcept_no": "R1", "rcept_dt": "20260720"},
            {"stock_code": "999999", "corp_name": "무관종목", "report_nm": "기타",
             "rcept_no": "R2", "rcept_dt": "20260720"},
            {"stock_code": "", "corp_name": "비상장", "report_nm": "기타",
             "rcept_no": "R3", "rcept_dt": "20260720"},
        ]}

    result = fetch_disclosures_for("key", {"005930"}, fetch_json=fake)
    assert [d.symbol for d in result] == ["005930"]
    assert result[0].filed_at == "2026-07-20"


def test_fetch_disclosures_error_isolated():
    def boom(params):
        raise ConnectionError("down")

    assert fetch_disclosures_for("key", {"005930"}, fetch_json=boom) == []
