"""시간대 정규화 — "거래량 급증"의 기준선.

일평균 거래량과 비교하면 장 초반은 항상 적게, 장 후반은 항상 많게 보인다.
올바른 비교: 오늘 10:30 누적거래량 vs 과거 N일 "10:30 시점" 누적거래량 분포의 z-score.

초기 구축: pykrx 분봉으로 과거 20일 프로파일 백필 (② 단계).
운영 갱신: 야간 배치가 당일 폴링 데이터로 슬롯별 평균·표준편차 갱신.
"""

from __future__ import annotations

from datetime import datetime


def slot_of(dt: datetime) -> str:
    """5분 슬롯 내림 — 09:00, 09:05, ..., 15:30."""
    return f"{dt.hour:02d}:{(dt.minute // 5) * 5:02d}"


def zscore(cum_volume: float, avg: float, std: float) -> float:
    """동시각 누적거래량 z-score. std가 비정상적으로 작을 때 폭주 방지 플로어."""
    effective_std = max(std, 1.0, avg * 0.05)
    return (cum_volume - avg) / effective_std


MIN_BASELINE_DAYS = 3  # 표본이 이보다 적은 슬롯은 baseline 미생성 (오탐 방지)


def rebuild_baselines(conn, *, lookback_days: int = 20) -> int:
    """intraday_observations → volume_baselines 재계산. 갱신된 (symbol, slot) 수 반환.

    각 (symbol, slot)에 대해 최근 lookback_days개 관측일의 누적거래량 평균·표준편차.
    당일 관측치는 제외 — 오늘의 서지가 자신의 기준선을 오염시키지 않게.
    """
    from datetime import date  # noqa: PLC0415
    from statistics import mean, pstdev  # noqa: PLC0415

    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT symbol, time_slot, obs_date, cum_volume FROM intraday_observations"
        " WHERE obs_date < ? ORDER BY symbol, time_slot, obs_date DESC",
        (today,),
    ).fetchall()

    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (row["symbol"], row["time_slot"])
        values = grouped.setdefault(key, [])
        if len(values) < lookback_days:  # obs_date DESC 정렬 → 최근 N일만
            values.append(row["cum_volume"])

    updated = 0
    for (symbol, slot), values in grouped.items():
        if len(values) < MIN_BASELINE_DAYS:
            continue
        conn.execute(
            "INSERT INTO volume_baselines (symbol, time_slot, avg_cum_volume, std_cum_volume, days)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(symbol, time_slot) DO UPDATE SET"
            " avg_cum_volume = excluded.avg_cum_volume, std_cum_volume = excluded.std_cum_volume,"
            " days = excluded.days, updated_at = datetime('now')",
            (symbol, slot, mean(values), pstdev(values), len(values)),
        )
        updated += 1
    conn.commit()
    return updated
