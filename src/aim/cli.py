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


def _build_price_lookup(settings, conn):
    """포트폴리오 평가용 시세 조회 — KIS(키 있으면) → pykrx 폴백."""
    if settings.kis_app_key and settings.kis_app_secret:
        try:
            from aim.data.kis.auth import KISAuth
            from aim.data.kis.intraday import KISIntradayProvider

            provider = KISIntradayProvider(
                conn, KISAuth(settings.kis_app_key, settings.kis_app_secret, settings.kis_env)
            )

            def kis_lookup(symbol: str):
                quotes = provider.snapshot([symbol])
                return (quotes[0].price, quotes[0].change_pct) if quotes else None

            return kis_lookup
        except Exception:  # noqa: BLE001
            pass
    from aim.data.krx import PykrxKRProvider

    return PykrxKRProvider().last_price


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
    p_brief.add_argument("--channel", default="console", choices=["console", "telegram", "discord"])

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

    p_pf = sub.add_parser("portfolio", help="내 포트폴리오 관리")
    pf_sub = p_pf.add_subparsers(dest="pf_command", required=True)
    pf_add = pf_sub.add_parser("add", help="보유 종목 등록/수정")
    pf_add.add_argument("symbol")
    pf_add.add_argument("quantity", type=float)
    pf_add.add_argument("avg_price", type=float)
    pf_add.add_argument("--name", default="")
    pf_rm = pf_sub.add_parser("rm")
    pf_rm.add_argument("symbol")
    pf_sub.add_parser("list", help="보유 종목 평가 (KIS→pykrx 시세)")
    pf_sub.add_parser("sync", help="KIS 계좌 잔고 동기화 (AIM_KIS_ACCOUNT_NO 필요)")

    p_watch = sub.add_parser("watch", help="관심종목 실시간 추적·시그널")
    p_watch.add_argument("--mock", action="store_true", help="데모 시나리오 재생 (키 불필요)")
    p_watch.add_argument("--interval", type=int, default=30, help="폴링 주기(초)")

    sub.add_parser("baseline-rebuild", help="관측치로 거래량 baseline 재계산 (야간/수동)")

    p_llm = sub.add_parser("test-llm", help="LLM 2-티어 연결 테스트 (deep=Codex, quick=MiniMax)")
    p_llm.add_argument("--tier", choices=["deep", "quick", "both"], default="both")

    p_an = sub.add_parser("analyze", help="종목 AI 토론 분석 — Bull/Bear → 판정 → 카드")
    p_an.add_argument("symbol", help="종목코드 (예: 005930)")
    p_an.add_argument("--date", default=None, help="기준일 YYYY-MM-DD (기본: 오늘)")
    p_an.add_argument("--show-debate", action="store_true", help="Bull/Bear 전문 출력")

    sub.add_parser("test-telegram", help="텔레그램 연결 테스트 (chat_id 미설정 시 자동 감지)")
    sub.add_parser("test-discord", help="디스코드 웹훅 연결 테스트")
    sub.add_parser("discord-setup", help="디스코드 서버 프로비저닝 — 채널·웹훅 자동 생성 + .env 기록")

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

        from aim.delivery.router import NotificationRouter, build_router

        if args.channel == "telegram":
            from aim.delivery.telegram import TelegramNotifier

            router = NotificationRouter(
                {}, [TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)]
            )
        elif args.channel == "discord":
            # 명시적 지정이므로 dry_run 무시, 콘솔 없이 디스코드 route만
            router = build_router(settings, respect_dry_run=False, include_console=False)
        else:
            from aim.delivery.console import ConsoleNotifier

            router = NotificationRouter({}, [ConsoleNotifier()])

        report_id = run_kr_close_briefing(settings, provider, router, date=args.date)
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

                from aim.delivery.router import NotificationRouter

                quotes, disclosures, demo_symbol = demo_scenario(BaselineRepository(conn))
                WatchlistRepository(conn).add(demo_symbol, "삼성전자", "KR")
                tracker = WatchTracker(
                    conn, quotes, disclosures, NotificationRouter({}, [ConsoleNotifier()])
                )
                for at in ("2026-07-20 10:00:00", "2026-07-20 10:05:00"):
                    fired = tracker.run_once(datetime.strptime(at, "%Y-%m-%d %H:%M:%S"))
                    print(f"\n[{at}] fired: {[s.kind for s in fired] or '(없음)'}")
            else:
                # 실전 모드 (현재: DART 공시 전용 — KIS 시세 폴링은 ③에서 추가)
                if not settings.dart_api_key:
                    print("AIM_DART_API_KEY 미설정 — .env에 키를 넣거나 --mock으로 데모를 실행하세요.")
                    print("키 발급(무료): https://opendart.fss.or.kr")
                    return

                from aim.delivery.router import build_router
                from aim.watch.baseline import rebuild_baselines
                from aim.watch.dart import OpenDartDisclosureProvider
                from aim.watch.provider import NullIntradayProvider

                router = build_router(settings)  # 디스코드 route별 + default, dry_run 반영

                dart = OpenDartDisclosureProvider(settings.dart_api_key, conn)
                dart.prime()  # 기동 시 당일 기존 공시는 조용히 처리 (알림 폭주 방지)

                # KIS 키가 있으면 장중 시세 폴링 활성 (거래량 서지·급변·COMBO)
                if settings.kis_app_key and settings.kis_app_secret:
                    from aim.data.kis.auth import KISAuth
                    from aim.data.kis.intraday import KISIntradayProvider

                    auth = KISAuth(settings.kis_app_key, settings.kis_app_secret, settings.kis_env)
                    quote_provider = KISIntradayProvider(conn, auth)
                    interval = max(args.interval, 30)
                    updated = rebuild_baselines(conn)
                    print(f"KIS 시세 폴링 활성 (env={settings.kis_env}) · baseline {updated}개 슬롯 갱신")
                else:
                    quote_provider = NullIntradayProvider()
                    interval = max(args.interval, 60)  # DART 쿼터 보호
                    print("KIS 키 미설정 — 공시 전용 모드")

                tracker = WatchTracker(conn, quote_provider, dart, router)
                print(f"추적 시작 (interval {interval}s, 창 07:00~19:00 · 시세는 09:00~15:30) — Ctrl+C로 중단")
                tracker.run_forever(poll_interval_sec=interval, window=("07:00", "19:00"))
        finally:
            conn.close()

    elif args.command == "baseline-rebuild":
        from aim.storage import db
        from aim.watch.baseline import rebuild_baselines

        conn = db.connect(settings.db_path)
        try:
            db.migrate(conn)
            updated = rebuild_baselines(conn)
        finally:
            conn.close()
        print(f"baseline 갱신: {updated}개 (symbol, slot)")

    elif args.command == "test-llm":
        import time as time_mod

        from aim.llm import build_llm

        tiers = ["deep", "quick"] if args.tier == "both" else [args.tier]
        for tier in tiers:
            try:
                client = build_llm(settings, tier)
            except RuntimeError as exc:
                print(f"[{tier}] 사용 불가: {exc}")
                continue
            print(f"[{tier}] {client.name} ({client.model}) 호출 중...")
            start = time_mod.time()
            try:
                reply = client.complete(
                    "당신은 금융 리서치 어시스턴트입니다. 한 문장으로만 답하세요.",
                    "코스피와 코스닥의 차이를 한 문장으로 설명해주세요.",
                )
                elapsed = time_mod.time() - start
                print(f"[{tier}] ✓ {elapsed:.1f}s — {reply[:120]}")
            except Exception as exc:  # noqa: BLE001
                print(f"[{tier}] ✗ 실패: {exc}")

    elif args.command == "portfolio":
        from aim.portfolio import render_portfolio_md, value_portfolio
        from aim.storage import db
        from aim.storage.repositories.portfolio import PortfolioRepository

        conn = db.connect(settings.db_path)
        try:
            db.migrate(conn)
            repo = PortfolioRepository(conn)

            if args.pf_command == "add":
                repo.upsert(args.symbol, args.quantity, args.avg_price, name=args.name)
                print(f"등록: {args.symbol} {args.quantity:,.0f}주 @ {args.avg_price:,.0f}")

            elif args.pf_command == "rm":
                repo.remove(args.symbol)
                print(f"삭제: {args.symbol}")

            elif args.pf_command == "sync":
                if not settings.kis_account_no:
                    print('AIM_KIS_ACCOUNT_NO 미설정 — .env에 "12345678-01" 형식으로 입력하세요.')
                    return
                from aim.data.kis.auth import KISAuth
                from aim.portfolio.kis_sync import fetch_balance

                auth = KISAuth(settings.kis_app_key, settings.kis_app_secret, settings.kis_env)
                positions = fetch_balance(auth, settings.kis_account_no)
                repo.replace_all(positions)
                print(f"KIS 계좌 동기화 완료 — 보유 {len(positions)}종목:")
                for p in positions:
                    print(f"  {p['name']}({p['symbol']}) {p['quantity']:,.0f}주 @ {p['avg_price']:,.0f}")

            else:  # list
                rows = repo.list_all()
                if not rows:
                    print("(보유 종목 없음 — aim portfolio add <코드> <수량> <평단가>)")
                    return
                # 시세: KIS 우선, 실패 시 pykrx 폴백
                lookup = _build_price_lookup(settings, conn)
                views, totals = value_portfolio(rows, lookup)
                print(render_portfolio_md(views, totals))
        finally:
            conn.close()

    elif args.command == "analyze":
        from aim.brain.debate import analyze_stock
        from aim.evidence.collector import collect_kr_evidence
        from aim.llm import build_llm
        from aim.storage import db

        print(f"증거 수집 중: {args.symbol} ...")
        evidence = collect_kr_evidence(args.symbol, args.date)
        print(f"수집 완료 — 증거 {len(evidence.items)}개" + (f", 실패 축: {evidence.gaps}" if evidence.gaps else ""))

        quick = build_llm(settings, "quick")
        deep = build_llm(settings, "deep")
        print(f"토론 시작 — Bull/Bear: {quick.name}({quick.model}), 판정: {deep.name}({deep.model})")

        conn = db.connect(settings.db_path)
        try:
            db.migrate(conn)
            result = analyze_stock(conn, evidence, quick, deep)
        finally:
            conn.close()

        if args.show_debate:
            print(f"\n─── Bull ───\n{result.bull_case}")
            print(f"\n─── Bear ───\n{result.bear_case}")
        print(f"\n{result.card_md}")
        print(f"\ndecision saved: {result.decision_id}")

    elif args.command == "test-telegram":
        import requests

        if not settings.telegram_bot_token:
            print("AIM_TELEGRAM_BOT_TOKEN 미설정 — 텔레그램 @BotFather에서 /newbot으로 발급 후 .env에 입력하세요.")
            return

        chat_id = settings.telegram_chat_id
        if not chat_id:
            # 자동 감지: 사용자가 봇에게 먼저 아무 메시지나 보냈다면 getUpdates에서 chat_id 확인 가능
            resp = requests.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates", timeout=15
            ).json()
            chats = {
                str(u["message"]["chat"]["id"]): u["message"]["chat"].get(
                    "username", u["message"]["chat"].get("first_name", "?")
                )
                for u in resp.get("result", [])
                if "message" in u
            }
            if not chats:
                print("chat_id 자동 감지 실패 — 먼저 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
                return
            for cid, name in chats.items():
                print(f"감지된 chat_id: {cid} ({name})")
            chat_id = next(iter(chats))
            print(f"→ .env에 추가하세요: AIM_TELEGRAM_CHAT_ID={chat_id}")

        from aim.delivery.telegram import TelegramNotifier

        ok = TelegramNotifier(settings.telegram_bot_token, chat_id).send(
            "AIM 연결 테스트", "텔레그램 연결 성공 ✅\n이 채널로 리포트와 관심종목 시그널이 발송됩니다."
        )
        print("발송 성공 ✓" if ok else "발송 실패 ✗ (토큰/chat_id 확인)")

    elif args.command == "test-discord":
        if not settings.discord_webhooks:
            print("AIM_DISCORD_WEBHOOK_* 미설정 — 디스코드 채널 편집 → 연동 → 웹훅 → URL 복사 후 .env에 입력하세요.")
            print("예: AIM_DISCORD_WEBHOOK_URL(기본), _KR(한국장), _US(미국장), _SIGNALS(시그널), _SURGE(급등주), _DISCLOSURE(공시)")
            return

        from aim.delivery.discord import DiscordNotifier

        route_desc = {
            "default": "기본(폴백)", "kr": "한국장 브리핑", "us": "미국장 브리핑",
            "signals": "관심종목 시그널", "surge": "급등주 시그널", "disclosure": "공시 알림",
            "weekly": "주간 리포트",
        }
        for route, url in sorted(settings.discord_webhooks.items()):
            desc = route_desc.get(route, route)
            ok = DiscordNotifier(url).send(
                f"AIM 채널 테스트 — {desc}",
                f"이 채널은 **{desc}** (route: `{route}`) 용도로 연결됐습니다 ✅",
            )
            print(f"[{route}] {desc}: {'발송 성공 ✓' if ok else '발송 실패 ✗'}")

    elif args.command == "discord-setup":
        from aim.config import ROOT
        from aim.delivery.discord_admin import DiscordAdmin, provision, update_env_file

        if not settings.discord_bot_token:
            print("AIM_DISCORD_BOT_TOKEN 미설정 — 봇 생성 후 토큰을 .env에 입력하세요:")
            print("  1. https://discord.com/developers/applications → New Application")
            print("  2. Bot 탭 → Reset Token → 복사 → .env의 AIM_DISCORD_BOT_TOKEN에 입력")
            print("  3. OAuth2 탭에서 CLIENT_ID 확인 후 아래 URL로 서버에 초대:")
            print("     https://discord.com/oauth2/authorize?client_id=<CLIENT_ID>&scope=bot&permissions=536870928")
            return

        admin = DiscordAdmin(settings.discord_bot_token)
        guilds = admin.list_guilds()
        if not guilds:
            print("봇이 참여한 서버가 없습니다 — 초대 URL로 서버에 먼저 초대하세요.")
            return
        if len(guilds) > 1 and not settings.discord_guild_id:
            print("봇이 여러 서버에 있습니다 — .env의 AIM_DISCORD_GUILD_ID에 대상 서버 ID를 지정하세요:")
            for g in guilds:
                print(f"  {g['id']}  {g['name']}")
            return
        guild = next(
            (g for g in guilds if g["id"] == settings.discord_guild_id), guilds[0]
        )
        print(f"대상 서버: {guild['name']}")

        result = provision(admin, guild["id"])
        for item in result.created:
            print(f"  + 생성: {item}")
        for item in result.reused:
            print(f"  = 재사용: {item}")
        for warning in result.warnings:
            print(f"  ! {warning}")

        if result.env_updates:
            changed = update_env_file(ROOT / ".env", result.env_updates)
            print(f"\n.env 갱신: {', '.join(changed) if changed else '(변경 없음 — 이미 최신)'}")
            print("다음: aim test-discord 로 채널별 발송 확인")


if __name__ == "__main__":
    main()
