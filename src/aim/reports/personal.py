"""개인화 섹션 (§10.6-2 — 마스터와 분리. 개인용 단계에선 사용자 1명).

v1: 내 포트폴리오 평가 요약. 서비스화 시 이 함수가 사용자별 팬아웃 워커의 단위 작업.
시세 조회 실패는 격리 — 포트폴리오가 비었거나 전부 실패해도 마스터 리포트는 발송된다.
"""

from __future__ import annotations

import logging
import sqlite3

from aim.portfolio import PriceLookup, render_portfolio_md, value_portfolio
from aim.storage.repositories.portfolio import PortfolioRepository

logger = logging.getLogger(__name__)


def build_personal_section(conn: sqlite3.Connection, price_lookup: PriceLookup) -> str:
    try:
        rows = PortfolioRepository(conn).list_all()
        if not rows:
            return ""
        views, totals = value_portfolio(rows, price_lookup)
        return render_portfolio_md(views, totals)
    except Exception:  # noqa: BLE001 — 개인 섹션 실패가 마스터 발송을 막지 않는다
        logger.exception("personal section failed")
        return ""
