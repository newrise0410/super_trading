from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceItem:
    key: str            # 인용 키 — 예: "flow.foreign_streak"
    category: str       # technical | flow | fundamental | event | news | market
    label: str          # 사람이 읽는 이름
    value: float | str
    unit: str = ""
    detail: str = ""    # 부가 설명 (예: "5일 누적 +3,214억")
    direction: str = "" # bullish | bearish | neutral — 룰이 태깅 (LLM 아님)

    def render(self) -> str:
        tag = {"bullish": "▲", "bearish": "▼", "neutral": "◆"}.get(self.direction, "◆")
        detail = f" — {self.detail}" if self.detail else ""
        return f"- [{self.key}] {tag} {self.label}: {self.value}{self.unit}{detail}"


@dataclass
class StockEvidence:
    """종목 판단의 단일 입력 — 판단 시 decisions.data_snapshot_json에 통째로 동결."""

    symbol: str
    name: str
    market: str
    as_of: str                      # YYYY-MM-DD (데이터 기준일)
    price: float
    change_pct: float
    items: list[EvidenceItem] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)  # 수집 실패한 축 — 명시적으로 기록

    def render_for_llm(self) -> str:
        lines = [
            f"## 검증된 증거 번들: {self.name} ({self.symbol}) — {self.as_of} 기준",
            f"현재가 {self.price:,.0f} ({self.change_pct:+.2f}%)",
            "",
            "아래 증거만 인용할 수 있다. 근거를 들 때는 반드시 [key]를 명시하라.",
        ]
        by_cat: dict[str, list[EvidenceItem]] = {}
        for item in self.items:
            by_cat.setdefault(item.category, []).append(item)
        for cat in ("technical", "flow", "fundamental", "event", "news", "market"):
            if cat in by_cat:
                lines.append(f"\n### {cat}")
                lines.extend(item.render() for item in by_cat[cat])
        if self.gaps:
            lines.append(f"\n(수집 실패 축: {', '.join(self.gaps)} — 이 부분은 판단에서 불확실성으로 간주)")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
