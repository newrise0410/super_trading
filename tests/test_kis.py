"""KIS 인증·장중 프로바이더 — 토큰 캐싱·파싱·실패 격리 (HTTP는 fake 주입)."""

from datetime import datetime, timedelta

import pytest

from aim.data.kis.auth import KISAuth
from aim.data.kis.intraday import KISIntradayProvider
from aim.storage import db
from aim.storage.repositories.watch import WatchlistRepository


class FakeTokenServer:
    def __init__(self):
        self.issued = 0

    def __call__(self, url, body):
        self.issued += 1
        assert url.endswith("/oauth2/tokenP")
        expires = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        return {"access_token": f"TOKEN-{self.issued}", "access_token_token_expired": expires}


def test_token_issued_once_and_cached(tmp_path):
    server = FakeTokenServer()
    auth = KISAuth("key", "secret", "prod", cache_path=tmp_path / "tok.json", fetch=server)

    assert auth.token() == "TOKEN-1"
    assert auth.token() == "TOKEN-1"       # 메모리 캐시
    assert server.issued == 1

    # 새 인스턴스 (프로세스 재시작 시뮬레이션) → 파일 캐시 재사용, 재발급 없음
    auth2 = KISAuth("key", "secret", "prod", cache_path=tmp_path / "tok.json", fetch=server)
    assert auth2.token() == "TOKEN-1"
    assert server.issued == 1


def test_expired_cache_reissues(tmp_path):
    server = FakeTokenServer()
    cache = tmp_path / "tok.json"
    auth = KISAuth("key", "secret", "prod", cache_path=cache, fetch=server)
    auth.token()

    # 캐시를 과거 만료로 조작
    import json
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["expires_at"] = "2020-01-01 00:00:00"
    cache.write_text(json.dumps(data), encoding="utf-8")

    auth2 = KISAuth("key", "secret", "prod", cache_path=cache, fetch=server)
    assert auth2.token() == "TOKEN-2"
    assert server.issued == 2


def test_env_and_key_validation(tmp_path):
    with pytest.raises(ValueError):
        KISAuth("", "secret")
    with pytest.raises(ValueError):
        KISAuth("key", "secret", "wrong-env")


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    WatchlistRepository(c).add("005930", "삼성전자")
    yield c
    c.close()


def _auth(tmp_path):
    return KISAuth("key", "secret", "prod", cache_path=tmp_path / "tok.json", fetch=FakeTokenServer())


def test_intraday_snapshot_parses_quote(conn, tmp_path):
    def fake_get(url, headers, params):
        assert headers["tr_id"] == "FHKST01010100"
        assert params["fid_input_iscd"] == "005930"
        return {"rt_cd": "0", "output": {
            "stck_prpr": "71000", "prdy_ctrt": "2.90",
            "acml_vol": "9400000", "acml_tr_pbmn": "665000000000",  # 6,650억
        }}

    p = KISIntradayProvider(conn, _auth(tmp_path), get_fn=fake_get)
    quotes = p.snapshot(["005930"])
    assert len(quotes) == 1
    q = quotes[0]
    assert q.name == "삼성전자"          # watchlist에서 이름 매핑
    assert q.price == 71000.0
    assert q.cum_volume == 9_400_000.0
    assert q.cum_value == 6650.0         # 원 → 억원


def test_intraday_error_rt_cd_skipped(conn, tmp_path):
    p = KISIntradayProvider(
        conn, _auth(tmp_path),
        get_fn=lambda u, h, prm: {"rt_cd": "1", "msg1": "조회 실패"},
    )
    assert p.snapshot(["005930"]) == []


def test_intraday_per_symbol_failure_isolated(conn, tmp_path):
    WatchlistRepository(conn).add("000660", "SK하이닉스")

    def flaky_get(url, headers, params):
        if params["fid_input_iscd"] == "005930":
            raise ConnectionError("boom")
        return {"rt_cd": "0", "output": {
            "stck_prpr": "198500", "prdy_ctrt": "1.0", "acml_vol": "1", "acml_tr_pbmn": "100000000",
        }}

    p = KISIntradayProvider(conn, _auth(tmp_path), get_fn=flaky_get)
    quotes = p.snapshot(["005930", "000660"])
    assert [q.symbol for q in quotes] == ["000660"]  # 실패 종목만 제외
