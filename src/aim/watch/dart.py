"""OpenDART 공시 폴러 — DisclosureProvider 실구현 (② 단계).

API: https://opendart.fss.or.kr/api/list.json (무료 키, 일 20,000콜 제한)

동작:
- 당일 전체 공시 목록을 최신순으로 페이징 조회 → 상장사(stock_code 있음)만 반환
- dart_seen 테이블(rcept_no)로 중복 제거 → "신규 공시"만 반환
- 이미 본 접수번호를 만나면 페이징 조기 종료 → 평시 폴링당 1콜 (1분 주기 = 일 ~700콜)
- prime(): 기동 시 당일 기존 공시를 조용히 seen 처리 — 시작 직후 알림 폭주 방지

제약:
- DART는 푸시 미제공 → 폴링이 유일. 공시는 장외에도 활발(실적 15:30~18:00 집중)
  → 폴링 창 07:00~19:00 권장
- list API는 접수 '일자'만 제공(시각 없음) → filed_at은 날짜, 탐지 시각은 시그널 fired_at
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from typing import Any, Callable

from aim.watch.models import Disclosure

logger = logging.getLogger(__name__)

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

STATUS_OK = "000"
STATUS_NO_DATA = "013"
STATUS_QUOTA_EXCEEDED = "020"

FetchJson = Callable[[dict[str, Any]], dict[str, Any]]


def _default_fetch(params: dict[str, Any]) -> dict[str, Any]:
    import requests  # noqa: PLC0415 — mock 경로 무의존 유지

    resp = requests.get(LIST_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_disclosures_for(
    api_key: str, symbols: set[str], *, days_back: int = 1, fetch_json: FetchJson | None = None
) -> list[Disclosure]:
    """장전 브리핑용 무상태 조회 — 최근 N일 공시 중 지정 종목만 (dedup 없음, 실패 시 빈 목록)."""
    from datetime import timedelta  # noqa: PLC0415

    fetch = fetch_json or _default_fetch
    try:
        data = fetch({
            "crtfc_key": api_key,
            "bgn_de": (date.today() - timedelta(days=days_back)).strftime("%Y%m%d"),
            "end_de": date.today().strftime("%Y%m%d"),
            "page_no": 1, "page_count": 100,
        })
        if data.get("status") != STATUS_OK:
            return []
        result = []
        for item in data.get("list") or []:
            stock_code = (item.get("stock_code") or "").strip()
            if stock_code not in symbols:
                continue
            rcept_dt = str(item.get("rcept_dt", ""))
            result.append(Disclosure(
                symbol=stock_code,
                corp_name=(item.get("corp_name") or "").strip(),
                title=(item.get("report_nm") or "").strip(),
                filed_at=f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}",
                url=VIEWER_URL.format(rcept_no=item.get("rcept_no", "")),
            ))
        return result
    except Exception:  # noqa: BLE001
        logger.exception("open-briefing disclosure fetch failed")
        return []


class OpenDartDisclosureProvider:
    def __init__(
        self,
        api_key: str,
        conn: sqlite3.Connection,
        *,
        fetch_json: FetchJson | None = None,
        max_pages: int = 5,
        page_count: int = 100,
    ) -> None:
        if not api_key:
            raise ValueError("AIM_DART_API_KEY 설정이 필요합니다 (.env)")
        self._api_key = api_key
        self._conn = conn
        self._fetch = fetch_json or _default_fetch
        self._max_pages = max_pages
        self._page_count = page_count

    # ── 공개 API ─────────────────────────────────────────────────

    def prime(self) -> int:
        """기동 시 당일 기존 공시를 조용히 seen 처리 (알림 폭주 방지). 처리 건수 반환."""
        self._prune_old_seen()
        _, marked = self._sweep(collect=False)
        logger.info("dart primed: %d existing filings marked seen", marked)
        return marked

    def fetch_new(self) -> list[Disclosure]:
        """직전 폴링 이후 신규 공시 (상장사만). 실패 시 빈 목록 — tracker를 죽이지 않는다."""
        try:
            disclosures, _ = self._sweep(collect=True)
            return disclosures
        except Exception:  # noqa: BLE001
            logger.exception("dart poll failed — returning empty")
            return []

    # ── 내부 ─────────────────────────────────────────────────────

    def _sweep(self, *, collect: bool) -> tuple[list[Disclosure], int]:
        """반환: (수집된 신규 공시 목록, seen 처리된 신규 접수번호 수)."""
        today = date.today().strftime("%Y%m%d")
        new_items: list[Disclosure] = []
        new_rcept_nos: list[str] = []

        for page_no in range(1, self._max_pages + 1):
            data = self._fetch({
                "crtfc_key": self._api_key,
                "bgn_de": today,
                "end_de": today,
                "page_no": page_no,
                "page_count": self._page_count,
            })
            status = data.get("status")
            if status == STATUS_NO_DATA:
                break
            if status == STATUS_QUOTA_EXCEEDED:
                logger.warning("dart daily quota exceeded (020) — backing off")
                break
            if status != STATUS_OK:
                logger.warning("dart api status %s: %s", status, data.get("message"))
                break

            items = data.get("list", [])
            hit_seen = False
            for item in items:
                rcept_no = str(item.get("rcept_no", ""))
                if not rcept_no:
                    continue
                if self._is_seen(rcept_no):
                    hit_seen = True  # 최신순이므로 이후는 대부분 기처리 — 이 페이지까지만
                    continue
                new_rcept_nos.append(rcept_no)

                if not collect:
                    continue
                stock_code = (item.get("stock_code") or "").strip()
                if not stock_code:
                    continue  # 비상장사
                rcept_dt = str(item.get("rcept_dt", today))
                new_items.append(Disclosure(
                    symbol=stock_code,
                    corp_name=(item.get("corp_name") or "").strip(),
                    title=(item.get("report_nm") or "").strip(),
                    filed_at=f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}",
                    url=VIEWER_URL.format(rcept_no=rcept_no),
                ))

            if hit_seen or len(items) < self._page_count:
                break

        if new_rcept_nos:
            self._conn.executemany(
                "INSERT OR IGNORE INTO dart_seen (rcept_no) VALUES (?)",
                [(r,) for r in new_rcept_nos],
            )
            self._conn.commit()
        return new_items, len(new_rcept_nos)

    def _is_seen(self, rcept_no: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM dart_seen WHERE rcept_no = ?", (rcept_no,)
        ).fetchone()
        return row is not None

    def _prune_old_seen(self) -> None:
        self._conn.execute("DELETE FROM dart_seen WHERE seen_at < datetime('now', '-7 days')")
        self._conn.commit()
