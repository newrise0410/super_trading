"""마스터 리포트 생성 (§10.6-2: 모든 사용자 공통 — 서비스화 시 1회 생성 N명 배포).

P1: 룰 기반 렌더링. P2에서 brain/ 멀티에이전트 산출물(주목 종목 카드, 레짐 코멘트)이
이 리포트에 섹션으로 합류한다.
"""

from __future__ import annotations

from aim.data.models import MarketSnapshot, StockMove

DISCLAIMER = "_본 리포트는 정보 제공 목적이며 투자 자문이 아닙니다. 투자 판단과 책임은 본인에게 있습니다._"


def _fmt_pct(pct: float) -> str:
    arrow = "🔺" if pct > 0 else ("🔻" if pct < 0 else "➖")
    return f"{arrow} {pct:+.2f}%"


def _fmt_flow(name: str, eok: float) -> str:
    sign = "순매수" if eok >= 0 else "순매도"
    return f"{name} {sign} {abs(eok):,.0f}억"


def _stock_lines(moves: list[StockMove]) -> str:
    lines = []
    for m in moves:
        note = f" — {m.note}" if m.note else ""
        lines.append(f"- **{m.name}** ({m.symbol}) {m.close:,.0f} {_fmt_pct(m.change_pct)}{note}")
    return "\n".join(lines) if lines else "- (해당 없음)"


def build_kr_close_briefing(snap: MarketSnapshot) -> str:
    """장 마감 브리핑 마크다운 (PLAN.md §4 스케줄 16:00)."""
    parts: list[str] = [f"# 🇰🇷 마감 브리핑 · {snap.date}\n"]

    parts.append("## 📊 지수 마감")
    for idx in snap.indices:
        parts.append(f"- **{idx.name}** {idx.close:,.2f} {_fmt_pct(idx.change_pct)}")
    if snap.usd_krw:
        parts.append(f"- **USD/KRW** {snap.usd_krw:,.1f}")

    if snap.flows:
        f = snap.flows
        parts.append("\n## 💰 수급 (KOSPI)")
        parts.append(f"- {_fmt_flow('외국인', f.foreign)} · {_fmt_flow('기관', f.institution)} · {_fmt_flow('개인', f.retail)}")

    parts.append("\n## 🚀 상승 특징주")
    parts.append(_stock_lines(snap.top_gainers))
    parts.append("\n## 📉 하락 특징주")
    parts.append(_stock_lines(snap.top_losers))
    parts.append("\n## 🔥 거래대금 상위")
    parts.append(_stock_lines(snap.most_traded))

    # P2에서 이 자리에 합류: 주목 종목 카드(근거+확신도), 레짐 판정, 시뮬 성과 리더보드(P3)
    parts.append("\n---\n" + DISCLAIMER)
    return "\n".join(parts)
