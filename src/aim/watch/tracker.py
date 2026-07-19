"""WatchTracker — 관심종목 폴링 → 룰 평가 → 시그널 발생 → 알림·기록.

run_once()가 단위 사이클 (테스트 가능). run_forever()는 장중 상주 루프.
시그널 발생 시: 쿨다운 체크 → signals 저장 → Notifier 발송 →
공시/COMBO는 knowledge store에 catalyst 팩트 기록 (다음 분석에 자동 반영).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime

from aim.delivery.router import NotificationRouter
from aim.knowledge import KnowledgeStore
from aim.storage.repositories.watch import (
    BaselineRepository,
    ObservationsRepository,
    SignalsRepository,
    WatchlistRepository,
)
from aim.watch.baseline import slot_of
from aim.watch.cooldown import FMT, Cooldown
from aim.watch.models import Signal
from aim.watch.provider import DisclosureProvider, IntradayProvider
from aim.watch.signals import (
    combo_signal,
    disclosure_signal,
    price_move_signal,
    volume_surge_signal,
)

logger = logging.getLogger(__name__)

_PRICE_WINDOW_MIN = 5.0    # 급변 감지 창 (분)
_HISTORY_MAXLEN = 60       # 심볼당 가격 이력 보관 (30초 폴링 × 30분)

# 시그널 종류 → 채널 route 체인 (앞에서부터 설정된 첫 채널로, 전부 없으면 default)
_SIGNAL_ROUTES: dict[str, tuple[str, ...]] = {
    "VOLUME_SURGE": ("surge", "signals"),
    "PRICE_MOVE": ("surge", "signals"),
    "COMBO": ("surge", "signals"),
    "DISCLOSURE": ("disclosure", "signals"),
}


class WatchTracker:
    def __init__(
        self,
        conn: sqlite3.Connection,
        quote_provider: IntradayProvider,
        disclosure_provider: DisclosureProvider,
        router: NotificationRouter,
        *,
        z_threshold: float = 3.0,
        price_threshold_pct: float = 3.0,
        cooldown_minutes: int = 30,
        quote_window: tuple[str, str] = ("09:00", "15:30"),  # 시세 폴링은 장중만
    ) -> None:
        self._watchlist = WatchlistRepository(conn)
        self._signals = SignalsRepository(conn)
        self._baselines = BaselineRepository(conn)
        self._observations = ObservationsRepository(conn)
        self._quote_window = quote_window
        self._knowledge = KnowledgeStore(conn)
        self._cooldown = Cooldown(self._signals, minutes=cooldown_minutes)
        self._quotes = quote_provider
        self._disclosures = disclosure_provider
        self._router = router
        self._z_threshold = z_threshold
        self._price_threshold_pct = price_threshold_pct
        # 심볼별 (시각, 가격) 이력 — 단기 급변 감지용
        self._history: dict[str, deque[tuple[datetime, float]]] = defaultdict(
            lambda: deque(maxlen=_HISTORY_MAXLEN)
        )

    # ── 단위 사이클 ──────────────────────────────────────────────

    def run_once(self, now: datetime) -> list[Signal]:
        symbols = self._symbols()
        if not symbols:
            logger.info("watchlist/portfolio empty — nothing to track")
            return []

        candidates: list[Signal] = []
        surges: dict[str, Signal] = {}
        disclosures_by_symbol: dict[str, Signal] = {}

        # 1) 시세 폴링 → 거래량 서지·단기 급변 (장중에만)
        hhmm = now.strftime("%H:%M")
        in_quote_session = self._quote_window[0] <= hhmm <= self._quote_window[1]
        quotes = self._quotes.snapshot(symbols) if in_quote_session else []
        for quote in quotes:
            quote_at = datetime.strptime(quote.at, FMT)

            # 관측치 축적 — 야간 rebuild_baselines()의 원천 (같은 슬롯은 마지막 값 유지)
            self._observations.record(
                quote.symbol, quote_at.date().isoformat(), slot_of(quote_at), quote.cum_volume
            )

            baseline = self._baselines.get(quote.symbol, slot_of(quote_at))
            if baseline is not None:
                surge = volume_surge_signal(
                    quote, baseline["avg_cum_volume"], baseline["std_cum_volume"],
                    z_threshold=self._z_threshold,
                )
                if surge:
                    candidates.append(surge)
                    surges[quote.symbol] = surge

            base = self._price_at_window_start(quote.symbol, quote_at)
            if base is not None:
                move = price_move_signal(
                    quote, base, _PRICE_WINDOW_MIN, threshold_pct=self._price_threshold_pct
                )
                if move:
                    candidates.append(move)
            self._history[quote.symbol].append((quote_at, quote.price))

        # 2) 공시 폴링 (관심종목만)
        for d in self._disclosures.fetch_new():
            if d.symbol not in symbols:
                continue
            sig = disclosure_signal(d)
            candidates.append(sig)
            disclosures_by_symbol[d.symbol] = sig

        # 3) COMBO 승격 — 서지 + 공시 동시(같은 사이클 또는 최근 30분 내 공시)
        for symbol, surge in surges.items():
            disclosure = disclosures_by_symbol.get(symbol) or self._recent_disclosure(symbol, now)
            if disclosure:
                candidates.append(combo_signal(surge, disclosure))

        # 4) 쿨다운 → 저장 → 발송 → knowledge 기록
        fired: list[Signal] = []
        for sig in candidates:
            if not self._cooldown.allow(sig.symbol, sig.kind, now):
                logger.debug("cooldown suppressed %s %s", sig.symbol, sig.kind)
                continue
            delivered = self._notify(sig)
            signal_id = self._signals.save(sig, now.strftime(FMT), delivered=delivered)
            if sig.kind in ("DISCLOSURE", "COMBO"):
                self._knowledge.upsert_fact(
                    market="KR", symbol=sig.symbol, fact_type="catalyst",
                    topic=f"signal:{signal_id}", content=sig.message,
                    as_of=now.date().isoformat(),
                )
            fired.append(sig)
        return fired

    # ── 상주 루프 ────────────────────────────────────────────────

    def run_forever(
        self, poll_interval_sec: int = 30, window: tuple[str, str] = ("09:00", "15:30")
    ) -> None:
        """상주 루프. window: 가동 시간대 — 시세 추적은 장중(09:00~15:30),
        공시 전용 모드는 ("07:00", "19:00") 권장 (실적 공시가 장 마감 후 집중)."""
        from aim.scheduler.calendar import KST, is_kr_trading_day  # noqa: PLC0415

        logger.info(
            "watch tracker started (interval %ss, window %s~%s, Ctrl+C to stop)",
            poll_interval_sec, window[0], window[1],
        )
        while True:
            now = datetime.now(KST).replace(tzinfo=None)
            in_session = is_kr_trading_day() and window[0] <= now.strftime("%H:%M") <= window[1]
            if in_session:
                try:
                    self.run_once(now)
                except Exception:  # noqa: BLE001 — 사이클 실패는 다음 폴링으로
                    logger.exception("watch cycle failed")
            time.sleep(poll_interval_sec)

    # ── 내부 ─────────────────────────────────────────────────────

    def _symbols(self) -> list[str]:
        """추적 대상 = 관심종목 ∪ 내 포트폴리오 보유 종목 (보유자는 항상 추적)."""
        wl = [row["symbol"] for row in self._watchlist.list_active()]
        pf = [
            row["symbol"]
            for row in self._watchlist.conn.execute("SELECT symbol FROM portfolio_positions")
        ]
        return list(dict.fromkeys(wl + pf))

    def _price_at_window_start(self, symbol: str, now: datetime) -> float | None:
        """now 기준 감지 창(5분) 이전~경계의 가장 오래된 가격."""
        window_start_price = None
        for at, price in self._history[symbol]:
            if (now - at).total_seconds() / 60 <= _PRICE_WINDOW_MIN:
                if window_start_price is None:
                    window_start_price = price
                break
            window_start_price = price  # 창 밖이면 계속 갱신 → 경계 직전 가격
        return window_start_price

    def _recent_disclosure(self, symbol: str, now: datetime) -> Signal | None:
        from datetime import timedelta  # noqa: PLC0415

        since = (now - timedelta(minutes=30)).strftime(FMT)
        rows = self._signals.recent(symbol, "DISCLOSURE", since)
        if not rows:
            return None
        row = rows[0]
        import json  # noqa: PLC0415

        return Signal(
            kind="DISCLOSURE", symbol=symbol, name="", severity=row["severity"],
            message=row["message"], payload=json.loads(row["payload_json"]),
        )

    def _notify(self, sig: Signal) -> bool:
        icon = {"info": "ℹ️", "notable": "🔔", "critical": "🚨"}.get(sig.severity, "🔔")
        title = f"{icon} 관심종목 시그널 — {sig.name or sig.symbol}"
        body = f"**{sig.name}** ({sig.symbol}) [{sig.kind}]\n{sig.message}"
        routes = _SIGNAL_ROUTES.get(sig.kind, ("signals",))
        return self._router.send(routes, title, body)
