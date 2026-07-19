"""디스코드 상담 봇 — #상담 채널·DM에서 LLM 대화 (aim chat).

- 게이트웨이(WebSocket) 방식: 봇이 디스코드로 연결 → 공개 서버·포트포워딩 불필요
- 요구: Developer Portal → Bot → Privileged Gateway Intents → **MESSAGE CONTENT INTENT** 활성화
- 프라이버시: **서버 오너(=사용자)에게만 응답** — 서버의 #상담 채널 또는 봇과의 DM.
  타인의 메시지는 무시 (포트폴리오·손익 정보 노출 방지). AIM_DISCORD_OWNER_ID로 오버라이드 가능
- 컨텍스트: 내 포트폴리오 평가(2분 캐시) + 최근 AI 판단 5건 — 대화는 채널별 최근 12턴 유지
- "진단" 입력 시 딥씽킹 전체 진단
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from aim.config import Settings
from aim.delivery.util import split_message

logger = logging.getLogger(__name__)

CONSULT_CHANNEL = "상담"
_CONTEXT_TTL_SEC = 120
_DISCORD_LIMIT = 1900


def _parse_why(text: str) -> str | None:
    """'/why 005930' · 'why AAPL' · '왜 005930' → 심볼 추출."""
    import re  # noqa: PLC0415

    m = re.match(r"^(?:/?why|왜)\s+([A-Za-z0-9]{1,10})$", text, re.IGNORECASE)
    return m.group(1).upper() if m else None

SYS_TMPL = """너는 'AIM 투자매니저' — 사용자 전용 AI 투자 상담사다.
아래는 사용자의 실제 포트폴리오와 최근 AI 판단 기록이다. 이를 근거로 대화하라.

{context}

원칙:
- 제공된 수치·기록만 인용하고, 없는 수치는 만들지 말고 모른다고 답하라
- 정보 제공·판단 근거 설명 중심. 매수/매도 지시 대신 "점검 관점" 프레임
- 한국어로 간결하게 (필요시 목록 사용)"""


class _ContextCache:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._value = ""
        self._at = 0.0

    def get(self) -> str:
        if time.time() - self._at < _CONTEXT_TTL_SEC and self._value:
            return self._value
        self._value = self._build()
        self._at = time.time()
        return self._value

    def _build(self) -> str:
        from aim.portfolio import render_portfolio_md, value_portfolio  # noqa: PLC0415
        from aim.portfolio.prices import make_lookup, usdkrw  # noqa: PLC0415
        from aim.data.krx import PykrxKRProvider  # noqa: PLC0415
        from aim.storage import db  # noqa: PLC0415
        from aim.storage.repositories.portfolio import PortfolioRepository  # noqa: PLC0415

        parts: list[str] = []
        conn = db.connect(self._settings.db_path)
        try:
            db.migrate(conn)
            try:
                rows = PortfolioRepository(conn).list_all()
                if rows:
                    kr = _kr_lookup(self._settings, conn)
                    views, totals = value_portfolio(rows, make_lookup(kr), usdkrw())
                    parts.append(render_portfolio_md(views, totals))
            except Exception:  # noqa: BLE001
                logger.exception("portfolio context failed")

            decisions = conn.execute(
                "SELECT symbol, name, action, confidence, created_at,"
                " json_extract(debate_log_json, '$[2].text') AS judge"
                " FROM decisions ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
            if decisions:
                lines = ["## 최근 AI 판단"]
                for d in decisions:
                    conf = f" {d['confidence']:.0%}" if d["confidence"] is not None else ""
                    lines.append(f"- {d['created_at'][:10]} {d['name']}({d['symbol']}): {d['action']}{conf}")
                parts.append("\n".join(lines))
        finally:
            conn.close()
        return "\n\n".join(parts) or "(포트폴리오·판단 기록 없음)"


def _kr_lookup(settings: Settings, conn):
    if settings.kis_app_key and settings.kis_app_secret:
        from aim.data.kis.auth import KISAuth  # noqa: PLC0415
        from aim.data.kis.intraday import KISIntradayProvider  # noqa: PLC0415

        provider = KISIntradayProvider(
            conn, KISAuth(settings.kis_app_key, settings.kis_app_secret, settings.kis_env)
        )

        def lookup(symbol: str):
            quotes = provider.snapshot([symbol])
            return (quotes[0].price, quotes[0].change_pct) if quotes else None

        return lookup
    from aim.data.krx import PykrxKRProvider  # noqa: PLC0415

    return PykrxKRProvider().last_price


def run_consult_bot(settings: Settings) -> None:
    try:
        import discord  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("discord.py 미설치 — pip install -e . 재실행 필요") from exc

    from aim.llm import build_llm  # noqa: PLC0415

    quick = build_llm(settings, "quick")
    deep = build_llm(settings, "deep")
    context = _ContextCache(settings)
    history: dict[int, deque[tuple[str, str]]] = defaultdict(lambda: deque(maxlen=12))

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    def _chat_reply(channel_id: int, text: str) -> str:
        convo = "\n".join(f"{who}: {what}" for who, what in history[channel_id])
        user = f"{convo}\n사용자: {text}" if convo else f"사용자: {text}"
        reply = quick.complete(SYS_TMPL.format(context=context.get()), user)
        history[channel_id].append(("사용자", text))
        history[channel_id].append(("AIM", reply))
        return reply

    def _why_reply(symbol: str) -> str:
        from aim.brain.why import render_why  # noqa: PLC0415
        from aim.storage import db  # noqa: PLC0415

        conn = db.connect(settings.db_path)
        try:
            db.migrate(conn)
            return render_why(conn, symbol)
        finally:
            conn.close()

    def _diagnose_reply() -> str:
        from aim.brain.diagnose import diagnose_portfolio  # noqa: PLC0415
        from aim.portfolio.prices import make_lookup, usdkrw  # noqa: PLC0415
        from aim.storage import db  # noqa: PLC0415

        conn = db.connect(settings.db_path)
        try:
            db.migrate(conn)
            result = diagnose_portfolio(
                conn, deep, make_lookup(_kr_lookup(settings, conn)), usdkrw()
            )
        finally:
            conn.close()
        return result or "포트폴리오가 비어있습니다 — aim portfolio add로 등록하세요."

    def _is_owner(message) -> bool:  # noqa: ANN001
        """서버 오너(=사용자)만 허용. env AIM_DISCORD_OWNER_ID가 있으면 그것을 기준으로."""
        override = getattr(settings, "discord_owner_id", "")
        if override:
            return str(message.author.id) == override
        if message.guild is not None:
            return message.author.id == message.guild.owner_id
        # DM: 봇이 속한 길드 중 하나라도 오너인 사람만
        return any(g.owner_id == message.author.id for g in client.guilds)

    @client.event
    async def on_ready() -> None:
        logger.info("consult bot ready: %s", client.user)
        print(f"상담 봇 접속 완료: {client.user} — #{CONSULT_CHANNEL} 채널 또는 DM으로 대화하세요 (Ctrl+C 종료)")

    @client.event
    async def on_message(message) -> None:  # noqa: ANN001
        if message.author.bot:
            return
        is_dm = message.guild is None
        if not is_dm and getattr(message.channel, "name", "") != CONSULT_CHANNEL:
            return
        if not _is_owner(message):
            logger.info("ignored non-owner message from %s", message.author.id)
            return
        text = message.content.strip()
        if not text:
            return
        async with message.channel.typing():
            plain = text.replace("!", "").strip()
            why_symbol = _parse_why(plain)
            if plain in ("진단", "진단해줘", "포트폴리오진단"):
                reply = await asyncio.to_thread(_diagnose_reply)
            elif why_symbol:
                reply = await asyncio.to_thread(_why_reply, why_symbol)
            else:
                reply = await asyncio.to_thread(_chat_reply, message.channel.id, text)
        for chunk in split_message(reply, _DISCORD_LIMIT):
            await message.channel.send(chunk)

    client.run(settings.discord_bot_token, log_handler=None)
