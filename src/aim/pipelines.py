"""리포트 파이프라인 — CLI와 스케줄러가 공유하는 오케스트레이션.

흐름: 데이터 수집 → (P2: 두뇌 판단) → 마스터 리포트 → 저장 → 개인 섹션 → 발송
"""

from __future__ import annotations

import logging
from datetime import date as date_cls

from aim.config import Settings
from aim.data.provider import MarketDataProvider
from aim.delivery.notifier import Notifier
from aim.reports.master import build_kr_close_briefing
from aim.reports.personal import build_personal_section
from aim.storage import db
from aim.storage.repositories.reports import ReportsRepository

logger = logging.getLogger(__name__)


def run_kr_close_briefing(
    settings: Settings,
    provider: MarketDataProvider,
    notifiers: list[Notifier],
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
        report_id = ReportsRepository(conn).save(
            kind="kr_close", market="KR", master_md=master_md, data=snap.to_dict()
        )
    finally:
        conn.close()

    personal_md = build_personal_section(user_context={}, master_md=master_md)
    final_md = master_md + (f"\n\n{personal_md}" if personal_md else "")

    title = f"🇰🇷 마감 브리핑 {date}"
    for notifier in notifiers:
        ok = notifier.send(title, final_md)
        logger.info("delivery via %s: %s", notifier.name, "ok" if ok else "FAILED")

    return report_id
