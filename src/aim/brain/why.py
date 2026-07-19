"""/why — 판단 근거 재현 (P4). decisions에 동결된 근거·토론·데이터 스냅샷을 렌더."""

from __future__ import annotations

import json
import sqlite3

from aim.storage.repositories.decisions import DecisionsRepository


def render_why(conn: sqlite3.Connection, symbol: str) -> str:
    row = DecisionsRepository(conn).latest_for_symbol(symbol)
    if row is None:
        return f"`{symbol}`에 대한 판단 기록이 없습니다 — `aim analyze {symbol}`로 분석을 먼저 실행하세요."

    rationale = json.loads(row["rationale_json"])
    risks = json.loads(row["risks_json"])
    debate = json.loads(row["debate_log_json"])
    snapshot = json.loads(row["data_snapshot_json"])

    conf = f" [확신도 {row['confidence']:.0%}]" if row["confidence"] is not None else ""
    lines = [
        f"## 🔎 /why {row['name']} ({row['symbol']})",
        f"**판정: {row['action']}**{conf} · {row['created_at'][:16]} · 전략 {row['strategy']}",
    ]

    if rationale:
        lines.append("\n**근거** (판단 시점 데이터 인용):")
        for i, r in enumerate(rationale, 1):
            key = f" `{r['evidence_key']}`" if r.get("evidence_key") else ""
            lines.append(f"{i}. {r.get('text', '')}{key}")

    if risks:
        lines.append("\n**리스크 (반대 논점)**:")
        lines.extend(f"- {r.get('text', '')}" for r in risks)

    if row["entry_price"] and row["target_price"] and row["stop_price"]:
        lines.append(
            f"\n**시나리오**: 진입 {row['entry_price']:,.0f} / 목표 {row['target_price']:,.0f}"
            f" / 손절 {row['stop_price']:,.0f} (지평 {row['horizon'] or '?'})"
        )

    bull = next((t["text"] for t in debate if t.get("role") == "bull"), "")
    bear = next((t["text"] for t in debate if t.get("role") == "bear"), "")
    if bull or bear:
        lines.append("\n**토론 요약**:")
        if bull:
            lines.append(f"- 🐂 Bull: {bull[:300]}{'…' if len(bull) > 300 else ''}")
        if bear:
            lines.append(f"- 🐻 Bear: {bear[:300]}{'…' if len(bear) > 300 else ''}")

    as_of = snapshot.get("as_of", "")
    n_items = len(snapshot.get("items", []))
    lines.append(f"\n_판단 시점 증거 {n_items}개 동결됨 ({as_of} 기준) — 이력: `/history {symbol}`_")

    if row["outcome_return_5d"] is not None:
        lines.append(f"**사후 결과**: 5일 수익률 {row['outcome_return_5d']:+.1f}%")
    return "\n".join(lines)
