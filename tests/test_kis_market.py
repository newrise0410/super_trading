"""KIS 시장 스냅샷 프로바이더 — 실응답 형태 fake로 파싱 검증."""

import pytest

from aim.data.kis.market import KISMarketProvider
from aim.storage import db


class FakeAuth:
    env = "prod"
    base_url = "https://x"

    def headers(self, tr_id, custtype="P"):
        return {"tr_id": tr_id}


def _investor_payload(ymd="20260716"):
    return {"rt_cd": "0", "output": [{
        "stck_bsop_date": ymd,
        "bstp_nmix_prpr": "6820.60", "bstp_nmix_prdy_vrss": "-463.81",
        "bstp_nmix_prdy_ctrt": "-6.37",
        "frgn_ntby_tr_pbmn": "-1366513",   # 백만원 → -13,665억
        "orgn_ntby_tr_pbmn": "-2383101",
        "prsn_ntby_tr_pbmn": "3664672",
    }]}


def _volume_rank_payload():
    return {"rt_cd": "0", "output": [
        {"hts_kor_isnm": "SK하이닉스", "mksc_shrn_iscd": "000660", "stck_prpr": "1842000",
         "prdy_ctrt": "-11.53", "acml_vol": "5608812", "acml_tr_pbmn": "10416500000000"},
        {"hts_kor_isnm": "삼성전자", "mksc_shrn_iscd": "005930", "stck_prpr": "255000",
         "prdy_ctrt": "-8.77", "acml_vol": "27001478", "acml_tr_pbmn": "6939400000000"},
        {"hts_kor_isnm": "반등주", "mksc_shrn_iscd": "111111", "stck_prpr": "10000",
         "prdy_ctrt": "3.10", "acml_vol": "1000000", "acml_tr_pbmn": "1000000000"},
    ]}


@pytest.fixture
def provider(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)

    def fake_get(url, headers, params):
        if "inquire-investor-daily-by-market" in url:
            return _investor_payload()
        if "volume-rank" in url:
            return _volume_rank_payload()
        raise AssertionError(f"unexpected url {url}")

    yield KISMarketProvider(conn, FakeAuth(), get_fn=fake_get)
    conn.close()


def test_snapshot_indices_and_flows(provider, monkeypatch):
    monkeypatch.setattr("aim.data.kis.market.time.sleep", lambda s: None)
    snap = provider.close_snapshot("2026-07-16")

    assert [i.name for i in snap.indices] == ["KOSPI", "KOSDAQ"]
    kospi = snap.indices[0]
    assert kospi.close == 6820.60 and kospi.change_pct == -6.37

    assert snap.flows.foreign == -13665      # 백만원 → 억원
    assert snap.flows.institution == -23831
    assert snap.flows.retail == 36647


def test_snapshot_movers_from_volume_rank(provider, monkeypatch):
    monkeypatch.setattr("aim.data.kis.market.time.sleep", lambda s: None)
    snap = provider.close_snapshot("2026-07-16")

    assert snap.most_traded[0].name == "SK하이닉스"
    assert snap.most_traded[0].value == pytest.approx(104165, abs=1)  # 원 → 억
    assert [m.name for m in snap.top_gainers] == ["반등주"]           # 양수만
    assert snap.top_losers[0].name == "SK하이닉스"                     # 최대 하락 우선


def test_snapshot_axis_failure_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("aim.data.kis.market.time.sleep", lambda s: None)
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)

    def flaky_get(url, headers, params):
        if "volume-rank" in url:
            return _volume_rank_payload()
        raise ConnectionError("index api down")

    snap = KISMarketProvider(conn, FakeAuth(), get_fn=flaky_get).close_snapshot("2026-07-16")
    assert snap.indices == [] and snap.flows is None   # 지수 축 실패 격리
    assert len(snap.most_traded) == 3                  # 순위 축은 정상
    conn.close()


def test_index_quotes(tmp_path, monkeypatch):
    monkeypatch.setattr("aim.data.kis.market.time.sleep", lambda s: None)
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)

    def fake_get(url, headers, params):
        assert "inquire-index-price" in url and headers["tr_id"] == "FHPUP02100000"
        value = {"0001": ("6820.60", "-6.37"), "1001": ("791.84", "-4.53")}[params["FID_INPUT_ISCD"]]
        return {"rt_cd": "0", "output": {"bstp_nmix_prpr": value[0], "bstp_nmix_prdy_ctrt": value[1]}}

    quotes = KISMarketProvider(conn, FakeAuth(), get_fn=fake_get).index_quotes()
    assert quotes == [("KOSPI", 6820.60, -6.37), ("KOSDAQ", 791.84, -4.53)]
    conn.close()


def test_diagnose_with_fake_llm(tmp_path):
    from aim.brain.diagnose import diagnose_portfolio
    from aim.storage.repositories.portfolio import PortfolioRepository

    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    PortfolioRepository(conn).upsert("AAPL", 2, 150, name="애플", market="US")

    class FakeLLM:
        name, model = "fake", "f1"

        def complete(self, system, user):
            assert "애플" in user           # 평가표가 입력으로 전달됨
            return "### 구성 요약\n집중도 높음"

    result = diagnose_portfolio(conn, FakeLLM(), lambda s, m: (200.0, 1.0), fx_usdkrw=1300.0)
    assert "AI 진단" in result and "집중도 높음" in result

    saved = conn.execute("SELECT kind FROM reports ORDER BY id DESC LIMIT 1").fetchone()
    assert saved["kind"] == "portfolio_diag"
    conn.close()
