"""토론 파이프라인 v1 — TradingAgents 구조 차용 (Apache 2.0).

흐름: 증거 번들 → Bull(quick) → Bear(quick, Bull 반박) → 판정(deep, 구조화 JSON)
     → decisions 기록(근거=evidence key 인용) → knowledge에 thesis/risk 팩트 → 카드 렌더

원칙: 애널리스트는 증거 번들 밖 수치 인용 금지. 판정은 JSON 강제 (파싱 실패 시 예외).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from aim.evidence.models import StockEvidence
from aim.knowledge import KnowledgeStore
from aim.llm.base import LLMClient
from aim.storage.repositories.decisions import DecisionsRepository

logger = logging.getLogger(__name__)

STRATEGY = "ai_debate_v1"

BULL_SYS = """당신은 강세론(Bull) 애널리스트다. 제공된 증거 번들만 사용해 이 종목의 매수 논거를 구축하라.
규칙: 번들에 없는 수치·사실을 만들어내지 마라. 근거마다 [key]를 인용하라. 5줄 이내, 한국어."""

BEAR_SYS = """당신은 약세론(Bear) 애널리스트다. 제공된 증거 번들과 강세론자의 주장을 읽고,
매수를 반대하는 논거와 강세론의 약점을 지적하라.
규칙: 번들에 없는 수치·사실을 만들어내지 마라. 근거마다 [key]를 인용하라. 5줄 이내, 한국어."""

JUDGE_SYS = """당신은 리서치 총괄 판정자다. 증거 번들과 Bull/Bear 토론을 평가해 최종 판단을 내려라.

반드시 아래 JSON 형식으로만 답하라 (다른 텍스트 금지):
{
  "action": "BUY" | "WATCH" | "AVOID",
  "confidence": 0~100 정수,
  "summary": "판단 요약 한 문장 (한국어)",
  "entry": 진입가 숫자 또는 null,
  "target": 목표가 숫자 또는 null,
  "stop": 손절가 숫자 또는 null,
  "horizon": "5d" | "20d",
  "rationale": [{"evidence_key": "번들의 key", "text": "근거 설명"}],
  "risks": [{"text": "리스크 설명 (Bear 논점 반영)"}]
}

규칙: rationale의 evidence_key는 반드시 번들에 존재하는 key만. 확신도는 증거 강도에 비례해 보수적으로.
가격 시나리오(entry/target/stop)는 BUY일 때만 제시, 아니면 null."""


@dataclass
class AnalysisResult:
    decision_id: str
    action: str
    confidence: float          # 0~1
    summary: str
    card_md: str
    verdict: dict[str, Any]
    bull_case: str
    bear_case: str


def analyze_stock(
    conn: sqlite3.Connection,
    evidence: StockEvidence,
    quick: LLMClient,
    deep: LLMClient,
    *,
    report_id: str | None = None,
) -> AnalysisResult:
    ev_md = evidence.render_for_llm()

    # 축적된 종목 지식 주입 (§13) — 과거 논지·리스크·사후 결과(반성 루프)가 다음 판단의 입력이 된다
    knowledge = KnowledgeStore(conn)
    context = knowledge.get_context(evidence.symbol)
    if context:
        ev_md += "\n\n## 축적된 종목 지식 (과거 분석·결과)\n" + KnowledgeStore.render_context(context)

    bull = quick.complete(BULL_SYS, ev_md)
    bear = quick.complete(BEAR_SYS, f"{ev_md}\n\n## 강세론자의 주장\n{bull}")

    judge_input = f"{ev_md}\n\n## 강세론 (Bull)\n{bull}\n\n## 약세론 (Bear)\n{bear}"
    verdict = _parse_verdict(deep.complete(JUDGE_SYS, judge_input))

    confidence = max(0.0, min(1.0, float(verdict.get("confidence", 0)) / 100))
    action = str(verdict.get("action", "WATCH")).upper()

    decision_id = DecisionsRepository(conn).save(
        market=evidence.market,
        symbol=evidence.symbol,
        name=evidence.name,
        action=action,
        strategy=STRATEGY,
        confidence=confidence,
        horizon=verdict.get("horizon"),
        entry_price=_num(verdict.get("entry")),
        target_price=_num(verdict.get("target")),
        stop_price=_num(verdict.get("stop")),
        rationale=verdict.get("rationale", []),
        risks=verdict.get("risks", []),
        debate_log=[
            {"role": "bull", "model": quick.model, "text": bull},
            {"role": "bear", "model": quick.model, "text": bear},
            {"role": "judge", "model": deep.model, "text": json.dumps(verdict, ensure_ascii=False)},
        ],
        data_snapshot=evidence.to_dict(),
        report_id=report_id,
    )

    # 지식저장소: 논지·리스크 축적 (재분석 시 같은 topic이 대체됨)
    knowledge = KnowledgeStore(conn)
    knowledge.upsert_fact(
        market=evidence.market, symbol=evidence.symbol, fact_type="thesis", topic="ai_debate",
        content=f"[{action}, 확신도 {confidence:.0%}] {verdict.get('summary', '')}",
        as_of=evidence.as_of, confidence=confidence, source_decision_id=decision_id,
    )
    risks = verdict.get("risks", [])
    if risks:
        knowledge.upsert_fact(
            market=evidence.market, symbol=evidence.symbol, fact_type="risk", topic="ai_debate",
            content=" / ".join(r.get("text", "") for r in risks[:3]),
            as_of=evidence.as_of, source_decision_id=decision_id,
        )

    card = render_card(evidence, verdict, action, confidence)
    return AnalysisResult(
        decision_id=decision_id, action=action, confidence=confidence,
        summary=verdict.get("summary", ""), card_md=card, verdict=verdict,
        bull_case=bull, bear_case=bear,
    )


def render_card(
    evidence: StockEvidence, verdict: dict[str, Any], action: str, confidence: float
) -> str:
    """주목 종목 카드 (PLAN.md §4 포맷)."""
    icon = {"BUY": "📌", "WATCH": "👀", "AVOID": "🚫"}.get(action, "👀")
    lines = [f"{icon} **{evidence.name}** ({evidence.symbol}) — {action} [확신도 {confidence:.0%}]"]

    rationale = verdict.get("rationale", [])
    if rationale:
        numbered = " ".join(
            f"{'①②③④⑤'[i] if i < 5 else f'({i+1})'} {r.get('text', '')}"
            for i, r in enumerate(rationale[:4])
        )
        lines.append(f"├ 근거: {numbered}")
    risks = verdict.get("risks", [])
    if risks:
        lines.append(f"├ 리스크: {risks[0].get('text', '')}")

    entry, target, stop = _num(verdict.get("entry")), _num(verdict.get("target")), _num(verdict.get("stop"))
    if entry and target and stop:
        up = (target / entry - 1) * 100
        down = (stop / entry - 1) * 100
        lines.append(
            f"├ 시나리오: 진입 {entry:,.0f} / 목표 {target:,.0f} ({up:+.1f}%) / 손절 {stop:,.0f} ({down:.1f}%)"
        )
    lines.append(f"└ {verdict.get('summary', '')}")
    return "\n".join(lines)


def _parse_verdict(raw: str) -> dict[str, Any]:
    """판정 JSON 추출 — 앞뒤 잡담·코드펜스 허용, 실패 시 예외."""
    text = re.sub(r"```(?:json)?|```", "", raw)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"판정 JSON 없음: {raw[:200]}")
    return json.loads(text[start : end + 1])


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
