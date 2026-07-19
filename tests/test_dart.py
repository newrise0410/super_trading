"""OpenDART 폴러 — prime·중복제거·페이징 조기종료·에러 격리 검증 (HTTP는 fake 주입)."""

from datetime import date

import pytest

from aim.storage import db
from aim.watch.dart import OpenDartDisclosureProvider


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    yield c
    c.close()


def _item(rcept_no, stock_code="005930", corp="삼성전자", title="단일판매ㆍ공급계약체결"):
    return {
        "rcept_no": rcept_no, "stock_code": stock_code, "corp_name": corp,
        "report_nm": title, "rcept_dt": date.today().strftime("%Y%m%d"),
        "corp_cls": "Y", "flr_nm": corp,
    }


class FakeDart:
    """페이지별 응답 스크립트 + 호출 카운터."""

    def __init__(self, pages_by_poll):
        self.pages_by_poll = pages_by_poll  # poll 회차 → {page_no: [items]}
        self.poll = -1
        self.calls = 0
        self.page_count = 2  # 테스트용 소형 페이지

    def __call__(self, params):
        self.calls += 1
        if params["page_no"] == 1:
            self.poll += 1
        pages = self.pages_by_poll[min(self.poll, len(self.pages_by_poll) - 1)]
        items = pages.get(params["page_no"], [])
        if not items and params["page_no"] > 1:
            return {"status": "013", "message": "no data"}
        return {"status": "000", "message": "ok", "list": items}


def _provider(conn, fake):
    return OpenDartDisclosureProvider("test-key", conn, fetch_json=fake, page_count=fake.page_count)


def test_prime_suppresses_existing_then_new_fires(conn):
    fake = FakeDart([
        {1: [_item("A1"), _item("A2")]},              # prime 시점의 기존 공시
        {1: [_item("B1", title="유상증자결정"), _item("A1"), _item("A2")]},  # 이후 폴링: B1만 신규
    ])
    p = _provider(conn, fake)

    assert p.prime() == 2                              # 기존 2건 조용히 seen
    new = p.fetch_new()
    assert [d.title for d in new] == ["유상증자결정"]  # 신규만 반환
    assert p.fetch_new() == []                         # 재폴링 — 중복 없음


def test_unlisted_filtered_but_marked_seen(conn):
    fake = FakeDart([
        {1: [_item("U1", stock_code=""), _item("L1")]},
    ])
    p = _provider(conn, fake)
    new = p.fetch_new()
    assert [d.symbol for d in new] == ["005930"]       # 비상장 제외
    assert p.fetch_new() == []                         # 비상장도 seen 처리돼 재등장 안 함


def test_paging_stops_early_on_seen(conn):
    # poll 0: 2페이지 (A1,A2 / A3) 전부 신규 → 2콜
    # poll 1: 신규 B1 + 기처리 A1 → 1페이지에서 조기 종료 → 1콜
    fake = FakeDart([
        {1: [_item("A1"), _item("A2")], 2: [_item("A3")]},
        {1: [_item("B1"), _item("A1")]},
    ])
    p = _provider(conn, fake)

    p.fetch_new()
    calls_after_first = fake.calls
    assert calls_after_first == 2

    new = p.fetch_new()
    assert [d.title for d in new] == ["단일판매ㆍ공급계약체결"]
    assert fake.calls == calls_after_first + 1         # 조기 종료로 1콜만 추가


def test_disclosure_fields(conn):
    fake = FakeDart([{1: [_item("R1")]}])
    p = _provider(conn, fake)
    d = p.fetch_new()[0]
    assert d.symbol == "005930"
    assert d.corp_name == "삼성전자"
    assert "rcpNo=R1" in d.url
    assert d.filed_at == date.today().isoformat()


def test_quota_exceeded_returns_empty(conn):
    p = OpenDartDisclosureProvider(
        "test-key", conn, fetch_json=lambda params: {"status": "020", "message": "quota"}
    )
    assert p.fetch_new() == []


def test_network_error_isolated(conn):
    def boom(params):
        raise ConnectionError("network down")

    p = OpenDartDisclosureProvider("test-key", conn, fetch_json=boom)
    assert p.fetch_new() == []                         # tracker를 죽이지 않는다


def test_missing_key_rejected(conn):
    with pytest.raises(ValueError):
        OpenDartDisclosureProvider("", conn)
