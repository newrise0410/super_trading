"""리포트 파이프라인 — CLI와 스케줄러가 공유하는 오케스트레이션.

흐름: 데이터 수집 → (P2: 두뇌 판단) → 마스터 리포트 → 저장 → 개인 섹션 → 발송
"""

from __future__ import annotations

import logging
from datetime import date as date_cls

from aim.config import Settings
from aim.data.provider import MarketDataProvider
from aim.delivery.router import NotificationRouter
from aim.reports.master import build_kr_close_briefing
from aim.reports.personal import build_personal_section
from aim.storage import db
from aim.storage.repositories.reports import ReportsRepository

logger = logging.getLogger(__name__)


def run_kr_close_briefing(
    settings: Settings,
    provider: MarketDataProvider,
    router: NotificationRouter,
    date: str | None = None,
) -> str:
    """KR 마감 브리핑 생성·저장·발송. report_id 반환."""
    date = date or date_cls.today().isoformat()
    logger.info("KR close briefing for %s", date)

    snap = provider.close_snapshot(date)
    master_md = build_kr_close_briefing(snap)

    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)

        # 전략 시뮬레이션 마감 사이클 + 리더보드 (P3) — 실패해도 브리핑은 발송
        try:
            from aim.simulation.engine import render_leaderboard, run_close_cycle  # noqa: PLC0415

            run_close_cycle(conn, snap, provider.last_price, date)
            leaderboard = render_leaderboard(conn)
            if leaderboard:
                master_md += f"\n\n{leaderboard}"
        except Exception:  # noqa: BLE001
            logger.exception("simulation cycle failed")

        # 반성 루프 — 5거래일 지난 판단의 사후 수익률 기록 (실패 격리)
        try:
            from aim.brain.reflect import evaluate_outcomes  # noqa: PLC0415

            evaluated = evaluate_outcomes(conn)
            if evaluated:
                logger.info("reflection: %d decisions evaluated", evaluated)
        except Exception:  # noqa: BLE001
            logger.exception("reflection failed")

        report_id = ReportsRepository(conn).save(
            kind="kr_close", market="KR", master_md=master_md, data=snap.to_dict()
        )
        # 개인화 레이어 (§10.6-2) — 내 포트폴리오 평가. 실패해도 마스터는 발송
        from aim.portfolio.prices import make_lookup, usdkrw  # noqa: PLC0415

        personal_md = build_personal_section(conn, make_lookup(provider.last_price), usdkrw())
    finally:
        conn.close()

    final_md = master_md + (f"\n\n{personal_md}" if personal_md else "")

    title = f"🇰🇷 마감 브리핑 {date}"
    router.send("kr", title, final_md)  # #한국장 채널 (미설정 시 default 폴백)

    return report_id


def run_us_close_briefing(
    settings: Settings, router: NotificationRouter, date: str | None = None
) -> str:
    """US 마감 브리핑 (P4) — yfinance 지수 + 환율 + 내 미국 보유."""
    from aim.portfolio.prices import kr_lookup_for, make_lookup, usdkrw as fetch_fx  # noqa: PLC0415
    from aim.reports.us import build_us_close_briefing, fetch_us_indices  # noqa: PLC0415

    date = date or date_cls.today().isoformat()
    logger.info("US close briefing for %s", date)

    indices = fetch_us_indices()
    fx = fetch_fx()

    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
        personal_md = build_personal_section(conn, make_lookup(kr_lookup_for(settings, conn)), fx)
        master_md = build_us_close_briefing(date, indices, fx, personal_md)
        report_id = ReportsRepository(conn).save(
            kind="us_close", market="US", master_md=master_md,
            data={"indices": indices, "usdkrw": fx},
        )
    finally:
        conn.close()

    router.send("us", f"🇺🇸 미국장 마감 브리핑 {date}", master_md)
    return report_id
