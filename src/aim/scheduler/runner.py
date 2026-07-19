"""스케줄 러너 — cron이 파이프라인을 직접 호출하지 않고 이벤트만 발행 (§10.6-5).

사용: `aim schedule` (포그라운드 상주). APScheduler는 lazy import — mock 경로 무의존 유지.
"""

from __future__ import annotations

import logging

from aim.config import Settings
from aim.events import EventBus
from aim.scheduler.calendar import KST, SCHEDULE_KST

logger = logging.getLogger(__name__)


def build_bus(settings: Settings) -> EventBus:
    """이벤트 → 파이프라인 핸들러 배선."""
    from aim.delivery.router import build_router  # noqa: PLC0415
    from aim.pipelines import run_kr_close_briefing  # noqa: PLC0415

    router = build_router(settings)  # 디스코드 route별 + default, dry_run 반영

    if settings.kis_app_key and settings.kis_app_secret:
        from aim.data.kis.auth import KISAuth  # noqa: PLC0415
        from aim.data.kis.market import KISMarketProvider  # noqa: PLC0415
        from aim.storage import db as db_mod  # noqa: PLC0415

        conn = db_mod.connect(settings.db_path)
        db_mod.migrate(conn)
        provider = KISMarketProvider(
            conn, KISAuth(settings.kis_app_key, settings.kis_app_secret, settings.kis_env)
        )
    else:
        from aim.data.krx import PykrxKRProvider  # noqa: PLC0415

        provider = PykrxKRProvider()

    from aim.pipelines import (  # noqa: PLC0415
        run_kr_open_briefing,
        run_us_close_briefing,
        run_us_open_briefing,
    )

    bus = EventBus()
    bus.subscribe(
        "market_open_kr",
        lambda **kw: run_kr_open_briefing(settings, router),
    )
    bus.subscribe(
        "market_close_kr",
        lambda **kw: run_kr_close_briefing(settings, provider, router),
    )

    def _review_decision_cards(**kw) -> None:
        """마감 후 결정 카드 감시 (§4.5) — 브리핑과 별개 핸들러 (실패 격리)."""
        from aim.llm import build_llm  # noqa: PLC0415
        from aim.socra.watchcards import review_cards  # noqa: PLC0415
        from aim.storage import db as db_mod2  # noqa: PLC0415

        card_conn = db_mod2.connect(settings.db_path)
        try:
            db_mod2.migrate(card_conn)
            try:
                quick = build_llm(settings, "quick")
            except RuntimeError:
                quick = None
            # 카드 보유 종목의 패널 일별 갱신 (다음 사이클의 페르소나 시뮬 입력)
            if quick is not None:
                from aim.panel import run_panel  # noqa: PLC0415

                symbols = [r["symbol"] for r in card_conn.execute(
                    "SELECT DISTINCT symbol FROM decision_cards WHERE status='active'"
                )]
                for symbol in symbols:
                    try:
                        run_panel(card_conn, settings, symbol, quick)
                    except Exception:  # noqa: BLE001
                        logger.exception("panel refresh failed: %s", symbol)
            review_cards(card_conn, settings, quick, router)
        finally:
            card_conn.close()

    bus.subscribe("market_close_kr", _review_decision_cards)
    bus.subscribe(
        "market_open_us",
        lambda **kw: run_us_open_briefing(settings, router),
    )
    bus.subscribe(
        "market_close_us",
        lambda **kw: run_us_close_briefing(settings, router),
    )
    return bus


def run_forever(settings: Settings) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: PLC0415
    from apscheduler.triggers.cron import CronTrigger  # noqa: PLC0415

    bus = build_bus(settings)
    sched = BlockingScheduler(timezone=KST)

    for event, (hhmm, guard) in SCHEDULE_KST.items():
        hour, minute = map(int, hhmm.split(":"))

        def fire(event: str = event, guard=guard) -> None:
            if not guard():
                logger.info("skip %s (not a trading day)", event)
                return
            bus.publish(event)

        sched.add_job(fire, CronTrigger(hour=hour, minute=minute), id=event)
        logger.info("scheduled %s at %s KST", event, hhmm)

    logger.info("scheduler started (Ctrl+C to stop)")
    sched.start()
