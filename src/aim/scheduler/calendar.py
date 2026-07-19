"""장 운영 캘린더 — KR/US 거래일·세션 판정.

TODO(P1 후반): KRX 휴장일 캘린더 반영 (pykrx 휴장일 조회 또는 수동 목록),
US는 pandas-market-calendars 검토 (prism-insight 사용 사례).
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")


def is_kr_trading_day(d: date | None = None) -> bool:
    d = d or datetime.now(KST).date()
    return d.weekday() < 5  # TODO: 공휴일 제외


def is_us_trading_day(d: date | None = None) -> bool:
    d = d or datetime.now(ET).date()
    return d.weekday() < 5  # TODO: 미국 공휴일 제외


# 리포트 발송 시각 (KST) — PLAN.md §4
SCHEDULE_KST = {
    "market_open_kr": ("08:30", is_kr_trading_day),
    "market_close_kr": ("16:00", is_kr_trading_day),
    "market_open_us": ("22:30", is_us_trading_day),
    "market_close_us": ("06:30", is_us_trading_day),
}
