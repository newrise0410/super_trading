"""패널 실행 — 같은 증거 번들을 6인의 렌즈에 통과시켜 합의 지표 산출.

- 일별 캐시 (panel_runs) — 같은 날 재실행 없음 (비용·일관성)
- 페르소나별 실패 격리 (하나가 파싱 실패해도 나머지 진행)
- 시뮬레이션(virtual_portfolios의 p_<persona> 전략)이 이 판정을 소비
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date as date_cls
from typing import Any

from aim.config import Settings
from aim.llm.base import LLMClient
from aim.panel.personas import COMMON_RULES, PERSONAS

logger = logging.getLogger(__name__)

DISCLAIMER = "각 인물의 공개된 투자 철학을 모사한 AI 관점입니다 — 실제 인물의 의견이 아니며, 참고용일 뿐 당신의 카드가 기준입니다."


def run_panel(
    conn: sqlite3.Connection,
    settings: Settings,
    symbol: str,
    quick: LLMClient,
    *,
    run_date: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """패널 실행 (일별 캐시). 반환: {symbol, name, date, verdicts, consensus, disclaimer}."""
    run_date = run_date or date_cls.today().isoformat()

    if not force:
        cached = conn.execute(
            "SELECT * FROM panel_runs WHERE symbol = ? AND run_date = ?", (symbol, run_date)
        ).fetchone()
        if cached:
            return {
                "symbol": symbol, "name": cached["name"], "date": run_date, "cached": True,
                "verdicts": json.loads(cached["verdicts_json"]),
                "consensus": json.loads(cached["consensus_json"]),
                "disclaimer": DISCLAIMER,
            }

    # 증거 수집 (소크라 엔진 재사용 — KIS 밸류에이션 포함)
    from aim.socra.engine import SocraEngine  # noqa: PLC0415

    collector = SocraEngine(conn, settings, quick, quick)
    evidence_md, name, _snap = collector._collect_evidence(symbol)  # noqa: SLF001

    verdicts: list[dict[str, Any]] = []
    for slug, display, persona_sys in PERSONAS:
        try:
            raw = quick.complete(persona_sys + "\n" + COMMON_RULES, f"[증거 — {name}({symbol})]\n{evidence_md}")
            text = re.sub(r"```(?:json)?|```", "", raw)
            verdict = json.loads(text[text.find("{"):text.rfind("}") + 1])
            from aim.socra.engine import _clean_reply  # noqa: PLC0415 — 증거키 누출 방지

            # 검증·강제 기권 (Codex 리뷰): stance enum, confidence 범위,
            # 데이터 부족(missing) 시 HOLD 강등 + confidence 상한 40
            stance = str(verdict.get("stance", "HOLD")).upper()
            if stance not in ("BUY", "HOLD", "AVOID"):
                stance = "HOLD"
            confidence = max(0, min(100, int(verdict.get("confidence") or 0)))
            missing = [str(m) for m in (verdict.get("missing") or [])][:5]
            if missing:
                if stance == "BUY":
                    stance = "HOLD"  # 근거 없는 매수 판정은 기권으로
                confidence = min(confidence, 40)

            verdicts.append({
                "persona": slug, "display": display,
                "stance": stance, "confidence": confidence,
                "thesis": _clean_reply(str(verdict.get("thesis", ""))),
                "key_metric": _clean_reply(str(verdict.get("key_metric", ""))),
                "missing": missing,
            })
        except Exception:  # noqa: BLE001 — 페르소나별 실패 격리
            logger.exception("persona %s failed", slug)

    consensus = _consensus(verdicts)
    conn.execute(
        "INSERT INTO panel_runs (symbol, run_date, name, verdicts_json, consensus_json)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(symbol, run_date) DO UPDATE SET verdicts_json = excluded.verdicts_json,"
        " consensus_json = excluded.consensus_json, name = excluded.name",
        (symbol, run_date, name, json.dumps(verdicts, ensure_ascii=False),
         json.dumps(consensus, ensure_ascii=False)),
    )
    conn.commit()
    return {"symbol": symbol, "name": name, "date": run_date, "cached": False,
            "verdicts": verdicts, "consensus": consensus, "disclaimer": DISCLAIMER}


def _consensus(verdicts: list[dict]) -> dict[str, Any]:
    counts = {"BUY": 0, "HOLD": 0, "AVOID": 0}
    for v in verdicts:
        counts[v["stance"]] = counts.get(v["stance"], 0) + 1
    total = sum(counts.values())
    majority = max(counts, key=counts.get) if total else "HOLD"
    return {
        "counts": counts, "total": total, "majority": majority,
        "agreement_pct": round(counts[majority] / total * 100) if total else 0,
    }


def todays_verdicts(conn: sqlite3.Connection, run_date: str) -> dict[str, dict]:
    """시뮬레이션용 — {symbol: {persona: verdict}} (해당 일자 패널 결과)."""
    result: dict[str, dict] = {}
    for row in conn.execute("SELECT * FROM panel_runs WHERE run_date = ?", (run_date,)):
        result[row["symbol"]] = {
            v["persona"]: v for v in json.loads(row["verdicts_json"])
        }
    return result
