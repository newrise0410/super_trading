"""내 포트폴리오 — 평가·렌더·KIS 동기화·트래커 연동·개인화 섹션 검증."""

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


def _lookup(symbol):
    return {"005930": (71000.0, 2.9), "000660": (198500.0, -1.1)}.get(symbol)


def test_valuation_math_and_weights(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("005930", 10, 65000, name="삼성전자")
    repo.upsert("000660", 2, 180000, name="SK하이닉스")

    views, totals = value_portfolio(repo.list_all(), _lookup)

    samsung = next(v for v in views if v.symbol == "005930")
    assert samsung.value == 710000.0
    assert samsung.pnl == pytest.approx(60000.0)
    assert samsung.pnl_pct == pytest.approx(9.23, abs=0.01)

    total_value = 710000.0 + 397000.0
    assert totals["value"] == pytest.approx(total_value)
    assert samsung.weight_pct == pytest.approx(710000.0 / total_value * 100)
    assert totals["pnl"] == pytest.approx(total_value - (650000 + 360000))


def test_valuation_missing_price_isolated(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("005930", 10, 65000, name="삼성전자")
    repo.upsert("999999", 5, 10000, name="상폐주")  # 시세 없음

    views, totals = value_portfolio(repo.list_all(), _lookup)
    missing = next(v for v in views if v.symbol == "999999")
    assert missing.price is None and missing.pnl is None
    assert totals["value"] is None  # 전체 합계는 불완전 → None (거짓 합계 방지)

    md = render_portfolio_md(views, totals)
    assert "시세 조회 불가" in md and "합계" not in md


def test_render_contains_pnl_and_weight(conn):
    repo = PortfolioRepository(conn)
    repo.upsert("005930", 10, 65000, name="삼성전자")
    views, totals = value_portfolio(repo.list_all(), _lookup)
    md = render_portfolio_md(views, totals)
    assert "내 포트폴리오" in md
    assert "+60,000" in md and "(+9.2%)" in md
    assert "합계" in md


def test_personal_section_empty_portfolio(conn):
    assert build_personal_section(conn, _lookup) == ""


def test_personal_section_failure_isolated(conn):
    PortfolioRepository(conn).upsert("005930", 10, 65000)

    def broken_lookup(symbol):
        raise ConnectionError("network down")

    assert build_personal_section(conn, broken_lookup) == ""  # 예외가 밖으로 새지 않음


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
            {"pdno": "035720", "prdt_name": "카카오", "hldg_qty": "0", "pchs_avg_pric": "50000"},  # 잔고 0 제외
        ]}

    positions = fetch_balance(FakeAuth(), "12345678-01", get_fn=fake_get)
    assert positions == [
        {"symbol": "005930", "name": "삼성전자", "quantity": 10.0, "avg_price": 65000.0}
    ]

    PortfolioRepository(conn).replace_all(positions)
    rows = PortfolioRepository(conn).list_all()
    assert len(rows) == 1 and rows[0]["name"] == "삼성전자"


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
    assert tracker._symbols() == ["005930", "000660"]  # 관심종목 ∪ 보유종목
