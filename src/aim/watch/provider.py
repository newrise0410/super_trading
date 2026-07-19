"""장중 데이터 프로바이더 프로토콜 + Mock.

실구현 예정: KISIntradayProvider (③ — REST 현재가 폴링 30초, 실전 키),
OpenDartDisclosureProvider (② — list.json 1분 폴링, 무료 키).
"""

from __future__ import annotations

from typing import Protocol

from aim.storage.repositories.watch import BaselineRepository
from aim.watch.models import Disclosure, IntradayQuote


class IntradayProvider(Protocol):
    def snapshot(self, symbols: list[str]) -> list[IntradayQuote]:
        """관심종목 현재 시세 1회 폴링."""
        ...


class DisclosureProvider(Protocol):
    def fetch_new(self) -> list[Disclosure]:
        """직전 폴링 이후 신규 공시."""
        ...


class NullIntradayProvider:
    """시세 미사용 모드 (예: DART 공시만 추적 — ② 단계, KIS 키 발급 전)."""

    def snapshot(self, symbols: list[str]) -> list[IntradayQuote]:
        return []


class MockIntradayProvider:
    """스크립트된 프레임 재생 — 호출할 때마다 다음 프레임 (마지막 프레임 반복)."""

    def __init__(self, frames: list[list[IntradayQuote]]) -> None:
        self._frames = frames
        self._i = 0

    def snapshot(self, symbols: list[str]) -> list[IntradayQuote]:
        frame = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        return [q for q in frame if q.symbol in symbols]


class MockDisclosureProvider:
    def __init__(self, batches: list[list[Disclosure]]) -> None:
        self._batches = batches
        self._i = 0

    def fetch_new(self) -> list[Disclosure]:
        if self._i >= len(self._batches):
            return []
        batch = self._batches[self._i]
        self._i += 1
        return batch


def demo_scenario(
    baseline_repo: BaselineRepository,
) -> tuple[MockIntradayProvider, MockDisclosureProvider, str]:
    """데모 시나리오: 삼성전자 — 평온한 10:00 → 10:05 수주공시 + 거래량 서지 + 급등.

    반환: (시세 프로바이더, 공시 프로바이더, 데모 심볼)
    """
    symbol, name = "005930", "삼성전자"

    # 동시각 누적거래량 프로파일 (과거 20일 가정)
    baseline_repo.upsert(symbol, "10:00", avg=5_000_000, std=500_000, days=20)
    baseline_repo.upsert(symbol, "10:05", avg=5_400_000, std=520_000, days=20)

    frames = [
        # 10:00 — 평온 (z ≈ 0.2)
        [IntradayQuote(symbol, name, price=70_000, change_pct=0.3,
                       cum_volume=5_100_000, cum_value=3_560, at="2026-07-20 10:00:00")],
        # 10:05 — 서지 (z ≈ 7.7) + 5분 내 +3.6%
        [IntradayQuote(symbol, name, price=72_500, change_pct=3.9,
                       cum_volume=9_400_000, cum_value=6_650, at="2026-07-20 10:05:00")],
    ]
    disclosures = [
        [],  # 10:00 — 없음
        [Disclosure(symbol=symbol, corp_name=name,
                    title="단일판매ㆍ공급계약체결 (2.1조원 규모 HBM 공급)",
                    filed_at="2026-07-20 10:03")],
    ]
    return MockIntradayProvider(frames), MockDisclosureProvider(disclosures), symbol
