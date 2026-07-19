"""내 포트폴리오 — 통화 인지 평가·렌더·KIS 동기화·트래커 연동·개인화 섹션 검증."""

import pytest

from aim.portfolio import render_portfolio_md, value_portfolio
from aim.portfolio.kis_sync import fetch_balance
from aim.reports.personal import build_personal_section
from aim.storage import db
from aim.storage.repositories.portfolio import PortfolioRepository


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    yield c
    c.close()


def _lookup(symbol, market):
    return {
        ("005930", "KR"): (71000.0, 2.9),
        ("AAPL", "US"): (200.0, -1.0),
        ("SCHD", "US"): (30.0, 0.5),
    }.get((symbol, market))


def test_valuation_krw_only(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("005930", 10, 65000, name="삼성전자")

    views, totals = value_portfolio(repo.list_all(), _lookup)
    v = views[0]
    assert v.currency == "KRW" and v.value == 710000.0
    assert v.pnl == pytest.approx(60000.0)
    assert totals["by_currency"]["KRW"]["value"] == pytest.approx(710000.0)
    assert totals["combined_krw"] == pytest.approx(710000.0)  # USD 없음 → 환율 불필요
    assert v.weight_pct == pytest.approx(100.0)


def test_valuation_mixed_currency_with_fx(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("005930", 10, 65000, name="삼성전자", market="KR")
    repo.upsert("AAPL", 2, 150, name="애플", market="US")

    views, totals = value_portfolio(repo.list_all(), _lookup, fx_usdkrw=1300.0)
    assert totals["by_currency"]["KRW"]["value"] == pytest.approx(710000.0)
    assert totals["by_currency"]["USD"]["value"] == pytest.approx(400.0)
    assert totals["combined_krw"] == pytest.approx(710000.0 + 400.0 * 1300)

    apple = next(v for v in views if v.symbol == "AAPL")
    assert apple.weight_pct == pytest.approx(400 * 1300 / (710000 + 520000) * 100)


def test_valuation_mixed_currency_without_fx_no_combined(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("005930", 10, 65000, market="KR")
    repo.upsert("AAPL", 2, 150, market="US")

    views, totals = value_portfolio(repo.list_all(), _lookup, fx_usdkrw=None)
    assert totals["combined_krw"] is None          # 환율 없으면 통합 합계 생략
    assert all(v.weight_pct is None for v in views)


def test_unknown_basis_hides_pnl(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("AAPL", 2, 0, name="애플", market="US")  # 평단가 미상

    views, totals = value_portfolio(repo.list_all(), _lookup, fx_usdkrw=1300.0)
    v = views[0]
    assert v.value == pytest.approx(400.0)
    assert v.pnl is None and v.pnl_pct is None      # 손익 왜곡 방지
    assert totals["all_basis"] is False

    md = render_portfolio_md(views, totals)
    assert "평단가 미입력" in md and "손익" not in md.split("\n")[1]


def test_missing_price_isolated(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("005930", 10, 65000, market="KR")
    repo.upsert("DEAD", 5, 10, name="상장폐지", market="US")  # 시세 없음

    views, totals = value_portfolio(repo.list_all(), _lookup, fx_usdkrw=1300.0)
    assert totals["combined_krw"] is None           # 불완전 → 통합 생략
    md = render_portfolio_md(views, totals)
    assert "시세 조회 불가" in md


def test_render_currency_symbols(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("AAPL", 2, 150, name="애플", market="US")
    views, totals = value_portfolio(repo.list_all(), _lookup, fx_usdkrw=1300.0)
    md = render_portfolio_md(views, totals)
    assert "$200.00" in md and "$400.00" in md
    assert "통합" in md and "환율 1,300" in md


def test_personal_section_failure_isolated(conn):
    PortfolioRepository(conn).upsert("005930", 10, 65000)

    def broken_lookup(symbol, market):
        raise ConnectionError("network down")

    assert build_personal_section(conn, broken_lookup) == ""


def test_kis_sync_parses_balance(conn):
    class FakeAuth:
        env = "prod"
        base_url = "https://x"

        def headers(self, tr_id, custtype="P"):
            assert tr_id == "TTTC8434R"
            return {}

    def fake_get(url, headers, params):
        assert params["CANO"] == "12345678" and params["ACNT_PRDT_CD"] == "01"
        return {"rt_cd": "0", "output1": [
            {"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "10", "pchs_avg_pric": "65000.00"},
            {"pdno": "035720", "prdt_name": "카카오", "hldg_qty": "0", "pchs_avg_pric": "50000"},
        ]}

    positions = fetch_balance(FakeAuth(), "12345678-01", get_fn=fake_get)
    assert positions == [
        {"symbol": "005930", "name": "삼성전자", "quantity": 10.0, "avg_price": 65000.0}
    ]


def test_kis_sync_bad_account_format():
    with pytest.raises(ValueError, match="형식"):
        fetch_balance(object(), "1234567801")


def test_tracker_includes_portfolio_symbols(conn):
    from aim.delivery.router import NotificationRouter
    from aim.storage.repositories.watch import BaselineRepository, WatchlistRepository
    from aim.watch.provider import demo_scenario
    from aim.watch.tracker import WatchTracker

    quotes, disclosures, _ = demo_scenario(BaselineRepository(conn))
    WatchlistRepository(conn).add("005930", "삼성전자")
    PortfolioRepository(conn).upsert("000660", 2, 180000, name="SK하이닉스")

    class Sink:
        name = "sink"

        def send(self, t, b):
            return True

    tracker = WatchTracker(conn, quotes, disclosures, NotificationRouter({}, [Sink()]))
    assert tracker._symbols() == ["005930", "000660"]
