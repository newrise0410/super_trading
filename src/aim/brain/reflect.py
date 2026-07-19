"""반성 루프 (P5) — 판단의 사후 수익률 기록 → 지식저장소 축적 → 다음 판단에 주입.

- 평가 대상: outcome_evaluated_at IS NULL이고 min_days(달력일) 이상 지난 판단
- 기준가: 판단 시점 동결 스냅샷의 price / 결과가: 판단일 이후 5번째 거래일 종가
- 적중 판정: BUY→상승, AVOID→하락이면 적중. WATCH는 관찰만
- outcome 팩트는 무기한 보존 (§13) — 확률 캘리브레이션의 원천
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Callable

from aim.knowledge import KnowledgeStore

logger = logging.getLogger(__name__)

# (symbol, market, decision_date) -> 판단일 이후 5번째 거래일 종가 | None(아직 데이터 부족)
PriceAfterFn = Callable[[str, str, str], float | None]


def _default_price_after(symbol: str, market: str, decision_date: str) -> float | None:
    start = date.fromisoformat(decision_date)
    end = start + timedelta(days=20)
    try:
        if market == "US":
            import yfinance as yf  # noqa: PLC0415

            hist = yf.Ticker(symbol).history(
                start=start.isoformat(), end=end.isoformat(), auto_adjust=False
            )
            closes = [float(v) for d, v in hist["Close"].items() if d.date() > start]
        else:
            from pykrx import stock  # noqa: PLC0415

            df = stock.get_market_ohlcv_by_date(
                (start + timedelta(days=1)).strftime("%Y%m%d"), end.strftime("%Y%m%d"), symbol
            )
            closes = [float(v) for v in df["종가"].tolist()]
        return closes[4] if len(closes) >= 5 else None
    except Exception:  # noqa: BLE001
        logger.exception("price_after failed for %s", symbol)
        return None


def evaluate_outcomes(
    conn: sqlite3.Connection, *, min_days: int = 7, price_after: PriceAfterFn | None = None
) -> int:
    """미평가 판단의 5일 수익률 기록. 평가된 건수 반환."""
    price_after = price_after or _default_price_after
    cutoff = (datetime.now() - timedelta(days=min_days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT * FROM decisions WHERE outcome_evaluated_at IS NULL AND created_at <= ?",
        (cutoff,),
    ).fetchall()

    knowledge = KnowledgeStore(conn)
    evaluated = 0
    for row in rows:
        snapshot = json.loads(row["data_snapshot_json"])
        base = float(snapshot.get("price") or 0)
        if base <= 0:
            continue
        after = price_after(row["symbol"], row["market"], row["created_at"][:10])
        if after is None:
            continue  # 거래일 5일 미충족 — 다음 실행에서 재시도

        ret = (after / base - 1) * 100
        conn.execute(
            "UPDATE decisions SET outcome_return_5d = ?, outcome_evaluated_at = datetime('now')"
            " WHERE id = ?",
            (round(ret, 2), row["id"]),
        )
        conn.commit()

        hit = {"BUY": ret > 0, "AVOID": ret < 0}.get(row["action"])
        verdict = "적중" if hit else ("빗나감" if hit is False else "관찰")
        conf = f", 확신도 {row['confidence']:.0%}" if row["confidence"] is not None else ""
        knowledge.upsert_fact(
            market=row["market"], symbol=row["symbol"], fact_type="outcome",
            topic=f"outcome:{row['decision_id']}",
            content=f"[{row['action']}{conf}] {row['created_at'][:10]} 판단 → 5거래일 {ret:+.1f}% — {verdict}",
            as_of=row["created_at"][:10], source_decision_id=row["decision_id"],
        )
        evaluated += 1
        logger.info("outcome: %s %s → %+.1f%% (%s)", row["symbol"], row["action"], ret, verdict)
    return evaluated
