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
