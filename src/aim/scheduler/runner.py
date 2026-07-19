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
    from aim.data.krx import PykrxKRProvider  # noqa: PLC0415
    from aim.delivery.router import build_router  # noqa: PLC0415
    from aim.pipelines import run_kr_close_briefing  # noqa: PLC0415

    router = build_router(settings)  # 디스코드 route별 + default, dry_run 반영

    bus = EventBus()
    bus.subscribe(
        "market_close_kr",
        lambda **kw: run_kr_close_briefing(settings, PykrxKRProvider(), router),
    )
    # TODO(P1+): market_open_kr / market_open_us / market_close_us 핸들러
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
