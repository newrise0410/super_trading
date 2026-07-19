"""시그널 룰 — 전부 결정론적 코드 (LLM 없음 = 비용 제로·무지연).

공시 분류·심각도, 거래량 서지(z-score), 단기 급변. COMBO 승격은 tracker에서 수행.
"""

from __future__ import annotations

from aim.watch.baseline import zscore
from aim.watch.models import Disclosure, IntradayQuote, Signal

# 공시 제목 키워드 → 카테고리 (순서 = 우선순위)
DISCLOSURE_CATEGORIES: list[tuple[str, list[str]]] = [
    ("delisting_risk", ["상장폐지", "관리종목", "불성실공시", "거래정지"]),
    ("supply_contract", ["단일판매", "공급계약", "수주"]),
    ("rights_issue", ["유상증자"]),
    ("bonus_issue", ["무상증자"]),
    ("treasury", ["자기주식", "자사주"]),
    ("earnings", ["잠정실적", "영업(잠정)실적", "실적공시"]),
    ("major_holder", ["최대주주", "주식등의대량보유", "임원ㆍ주요주주"]),
    ("merger", ["합병", "분할", "영업양수"]),
    ("litigation", ["소송"]),
]

CATEGORY_SEVERITY: dict[str, str] = {
    "delisting_risk": "critical",
    "supply_contract": "notable",
    "rights_issue": "notable",       # 통상 악재 — 방향 판단은 LLM 몫, 여기선 중요도만
    "earnings": "notable",
    "merger": "notable",
    "major_holder": "notable",
    "bonus_issue": "info",
    "treasury": "info",
    "litigation": "notable",
    "other": "info",
}

CATEGORY_LABEL: dict[str, str] = {
    "delisting_risk": "상폐/관리 위험",
    "supply_contract": "공급계약·수주",
    "rights_issue": "유상증자",
    "bonus_issue": "무상증자",
    "treasury": "자기주식",
    "earnings": "실적",
    "major_holder": "지분 변동",
    "merger": "합병·분할",
    "litigation": "소송",
    "other": "기타",
}


def classify_disclosure(title: str) -> str:
    for category, keywords in DISCLOSURE_CATEGORIES:
        if any(kw in title for kw in keywords):
            return category
    return "other"


def volume_surge_signal(
    quote: IntradayQuote, avg: float, std: float, *, z_threshold: float = 3.0
) -> Signal | None:
    z = zscore(quote.cum_volume, avg, std)
    if z < z_threshold:
        return None
    return Signal(
        kind="VOLUME_SURGE",
        symbol=quote.symbol,
        name=quote.name,
        severity="notable" if z < 5 else "critical",
        message=f"거래량 서지 — 동시각 대비 z={z:.1f} (누적 {quote.cum_volume:,.0f}주, {quote.change_pct:+.1f}%)",
        payload={"z": round(z, 2), "cum_volume": quote.cum_volume, "price": quote.price},
    )


def price_move_signal(
    quote: IntradayQuote, base_price: float, window_minutes: float, *, threshold_pct: float = 3.0
) -> Signal | None:
    if base_price <= 0:
        return None
    move_pct = (quote.price - base_price) / base_price * 100
    if abs(move_pct) < threshold_pct:
        return None
    direction = "급등" if move_pct > 0 else "급락"
    return Signal(
        kind="PRICE_MOVE",
        symbol=quote.symbol,
        name=quote.name,
        severity="notable",
        message=f"{window_minutes:.0f}분 내 {direction} {move_pct:+.1f}% ({base_price:,.0f} → {quote.price:,.0f})",
        payload={"move_pct": round(move_pct, 2), "window_minutes": window_minutes},
    )


def disclosure_signal(d: Disclosure) -> Signal:
    category = d.category or classify_disclosure(d.title)
    return Signal(
        kind="DISCLOSURE",
        symbol=d.symbol,
        name=d.corp_name,
        severity=CATEGORY_SEVERITY.get(category, "info"),
        message=f"공시 [{CATEGORY_LABEL.get(category, '기타')}] {d.title} ({d.filed_at})",
        payload={"category": category, "title": d.title, "filed_at": d.filed_at, "url": d.url},
    )


def combo_signal(surge: Signal, disclosure: Signal) -> Signal:
    """거래량 서지 ± 공시 동시 발생 = 가장 신뢰도 높은 시그널."""
    return Signal(
        kind="COMBO",
        symbol=surge.symbol,
        name=surge.name,
        severity="critical",
        message=f"공시발 수급 이벤트 — {disclosure.message} + {surge.message}",
        payload={"surge": surge.payload, "disclosure": disclosure.payload},
    )
