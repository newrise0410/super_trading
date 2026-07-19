"""AIM CLI.

예:
  python -m aim init-db
  python -m aim briefing kr-close --mock --channel console
  python -m aim briefing kr-close --date 2026-07-18
  python -m aim schedule
"""

from __future__ import annotations

import argparse
import logging
import sys

from aim.config import get_settings


def main() -> None:
    # Windows 콘솔(cp949)에서 이모지·한글 출력 보장
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="aim", description="나의 AI 투자 매니저")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="DB 생성/마이그레이션")

    p_brief = sub.add_parser("briefing", help="리포트 생성·발송")
    p_brief.add_argument("kind", choices=["kr-close"], help="리포트 종류 (P1: kr-close)")
    p_brief.add_argument("--date", default=None, help="YYYY-MM-DD (기본: 오늘)")
    p_brief.add_argument("--mock", action="store_true", help="캔드 데이터 사용 (의존성/네트워크 불필요)")
    p_brief.add_argument("--channel", default="console", choices=["console", "telegram"])

    sub.add_parser("schedule", help="정시 리포트 스케줄러 상주 실행")

    p_wl = sub.add_parser("watchlist", help="관심종목 관리")
    wl_sub = p_wl.add_subparsers(dest="wl_command", required=True)
    wl_add = wl_sub.add_parser("add")
    wl_add.add_argument("symbol")
    wl_add.add_argument("--name", default="")
    wl_add.add_argument("--market", default="KR")
    wl_sub.add_parser("list")
    wl_rm = wl_sub.add_parser("rm")
    wl_rm.add_argument("symbol")

    p_watch = sub.add_parser("watch", help="관심종목 실시간 추적·시그널")
    p_watch.add_argument("--mock", action="store_true", help="데모 시나리오 재생 (키 불필요)")
    p_watch.add_argument("--interval", type=int, default=30, help="폴링 주기(초)")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "init-db":
        from aim.storage import db

        conn = db.connect(settings.db_path)
        try:
            applied = db.migrate(conn)
        finally:
            conn.close()
        print(f"DB ready: {settings.db_path}")
        print(f"applied migrations: {applied or '(up to date)'}")

    elif args.command == "briefing":
        from aim.pipelines import run_kr_close_briefing

        if args.mock:
            from aim.data.provider import MockKRProvider

            provider = MockKRProvider()
        else:
            from aim.data.krx import PykrxKRProvider

            provider = PykrxKRProvider()

        if args.channel == "telegram":
            from aim.delivery.telegram import TelegramNotifier

            notifiers = [TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)]
        else:
            from aim.delivery.console import ConsoleNotifier

            notifiers = [ConsoleNotifier()]

        report_id = run_kr_close_briefing(settings, provider, notifiers, date=args.date)
        print(f"\nreport saved: {report_id}")

    elif args.command == "schedule":
        from aim.scheduler.runner import run_forever

        run_forever(settings)

    elif args.command == "watchlist":
        from aim.storage import db
        from aim.storage.repositories.watch import WatchlistRepository

        conn = db.connect(settings.db_path)
        try:
            db.migrate(conn)
            repo = WatchlistRepository(conn)
            if args.wl_command == "add":
                repo.add(args.symbol, args.name, args.market)
                print(f"added: {args.symbol} {args.name}")
            elif args.wl_command == "rm":
                repo.remove(args.symbol)
                print(f"removed: {args.symbol}")
            else:
                rows = repo.list_active()
                if not rows:
                    print("(관심종목 없음 — aim watchlist add <symbol> --name <이름>)")
                for row in rows:
                    print(f"{row['symbol']}  {row['name']}  [{row['market']}]")
        finally:
            conn.close()

    elif args.command == "watch":
        from datetime import datetime

        from aim.delivery.console import ConsoleNotifier
        from aim.storage import db
        from aim.watch.tracker import WatchTracker

        conn = db.connect(settings.db_path)
        try:
            db.migrate(conn)
            if args.mock:
                from aim.storage.repositories.watch import BaselineRepository, WatchlistRepository
                from aim.watch.provider import demo_scenario

                quotes, disclosures, demo_symbol = demo_scenario(BaselineRepository(conn))
                WatchlistRepository(conn).add(demo_symbol, "삼성전자", "KR")
                tracker = WatchTracker(conn, quotes, disclosures, [ConsoleNotifier()])
                for at in ("2026-07-20 10:00:00", "2026-07-20 10:05:00"):
                    fired = tracker.run_once(datetime.strptime(at, "%Y-%m-%d %H:%M:%S"))
                    print(f"\n[{at}] fired: {[s.kind for s in fired] or '(없음)'}")
            else:
                # 실전 모드 (현재: DART 공시 전용 — KIS 시세 폴링은 ③에서 추가)
                if not settings.dart_api_key:
                    print("AIM_DART_API_KEY 미설정 — .env에 키를 넣거나 --mock으로 데모를 실행하세요.")
                    print("키 발급(무료): https://opendart.fss.or.kr")
                    return

                from aim.delivery.telegram import TelegramNotifier
                from aim.watch.dart import OpenDartDisclosureProvider
                from aim.watch.provider import NullIntradayProvider

                notifiers = [ConsoleNotifier()]
                if not settings.dry_run and settings.telegram_bot_token:
                    notifiers.append(
                        TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
                    )

                dart = OpenDartDisclosureProvider(settings.dart_api_key, conn)
                dart.prime()  # 기동 시 당일 기존 공시는 조용히 처리 (알림 폭주 방지)

                tracker = WatchTracker(conn, NullIntradayProvider(), dart, notifiers)
                interval = max(args.interval, 60)  # DART 쿼터 보호 — 최소 60초
                print(f"공시 추적 시작 (interval {interval}s, 창 07:00~19:00) — Ctrl+C로 중단")
                tracker.run_forever(poll_interval_sec=interval, window=("07:00", "19:00"))
        finally:
            conn.close()


if __name__ == "__main__":
    main()
