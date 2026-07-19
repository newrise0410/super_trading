"""살아있는 결정 카드 감시 (§4.5) — 일일 리뷰: 가격 기준선 · 근거 diff · 재검토 조건.

- 근거 diff: 카드에 동결된 스냅샷의 direction(룰 태깅) vs 최신 수집 → 방향 반전만 알림
  (bullish↔bearish — "외인 5일 순매수 → 3일 순매도" 같은 질적 변화)
- 재검토 조건: 사용자의 자연어 조건을 quick LLM이 최신 증거와 대조해 발동 판정
- 중복 억제: 같은 (card, kind) 알림은 3일간 재발송 안 함
- 알림: 라우터 ("cards","signals",default 폴백) + 웹 재질문 링크
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any

from aim.config import Settings
from aim.llm.base import LLMClient

logger = logging.getLogger(__name__)

_FLIP = {("bullish", "bearish"), ("bearish", "bullish")}
ALERT_COOLDOWN_DAYS = 3
WEB_BASE = "http://localhost:8501"

RECHECK_EVAL = """사용자가 정한 재검토 조건 목록과 최신 시장 증거다.
각 조건이 현재 증거상 '발동'했는지 판정하라. 증거로 판단 불가한 조건은 발동 아님으로.

반드시 JSON만: {{"triggered": [발동한 조건의 0-기반 인덱스 목록]}}

[재검토 조건]
{conditions}

[최신 증거]
{evidence}"""


def _fmt(item: dict[str, Any]) -> str:
    unit = item.get("unit") or ""
    return f"{item['value']}{unit}"


def diff_evidence(old_items: list[dict], new_items: list[dict]) -> list[tuple[str, str]]:
    """방향 반전 감지 → [(kind, message)]."""
    old_map = {i["key"]: i for i in old_items}
    alerts = []
    for new in new_items:
        old = old_map.get(new["key"])
        if not old:
            continue
        pair = (old.get("direction") or "", new.get("direction") or "")
        if pair in _FLIP:
            arrow = "긍정→부정" if pair[0] == "bullish" else "부정→긍정"
            alerts.append((
                f"flip:{new['key']}",
                f"{new['label']}: {_fmt(old)} → {_fmt(new)} ({arrow} 반전)",
            ))
    return alerts


def review_cards(
    conn: sqlite3.Connection,
    settings: Settings,
    quick: LLMClient | None = None,
    router=None,
) -> list[dict[str, Any]]:
    """활성 카드 전수 리뷰. 알림 발생 카드 목록 반환 [{card_id, name, alerts}]."""
    from aim.socra.engine import SocraEngine  # noqa: PLC0415 — _collect_evidence 재사용

    cards = conn.execute(
        "SELECT * FROM decision_cards WHERE status = 'active'"
    ).fetchall()
    if not cards:
        return []

    collector = SocraEngine(conn, settings, quick or _NullLLM(), _NullLLM())
    results = []

    for card in cards:
        try:
            alerts = _review_one(conn, card, collector, quick)
        except Exception:  # noqa: BLE001 — 카드별 실패 격리
            logger.exception("card review failed: %s", card["card_id"])
            continue
        if not alerts:
            continue
        results.append({"card_id": card["card_id"], "name": card["name"],
                        "symbol": card["symbol"], "alerts": [m for _, m in alerts]})
        if router is not None:
            _notify(router, card, [m for _, m in alerts])
    return results


def _review_one(conn, card, collector, quick) -> list[tuple[str, str]]:
    evidence_md, _name, fresh = collector._collect_evidence(card["symbol"])  # noqa: SLF001
    snapshot = json.loads(card["evidence_snapshot_json"] or "{}")
    candidates: list[tuple[str, str]] = []

    # 1) 가격 기준선 (최신 종가 기준)
    price = fresh.get("price") or 0
    if price and card["target_price"] and price >= card["target_price"]:
        candidates.append(("price_target",
                           f"목표가 도달 — 현재 {price:,.0f} ≥ 목표 {card['target_price']:,.0f}"))
    if price and card["stop_price"] and price <= card["stop_price"]:
        candidates.append(("price_stop",
                           f"손절선 도달 — 현재 {price:,.0f} ≤ 손절 {card['stop_price']:,.0f}"))

    # 2) 근거 방향 반전
    if snapshot.get("items") and fresh.get("items"):
        candidates += diff_evidence(snapshot["items"], fresh["items"])

    # 3) 재검토 조건 (LLM 판정)
    conditions = json.loads(card["recheck_conditions"] or "[]")
    if conditions and quick is not None:
        try:
            raw = quick.complete(
                "너는 조건 판정기다. JSON만 출력하라.",
                RECHECK_EVAL.format(
                    conditions="\n".join(f"{i}. {c}" for i, c in enumerate(conditions)),
                    evidence=evidence_md,
                ),
            )
            text = re.sub(r"```(?:json)?|```", "", raw)
            triggered = json.loads(text[text.find("{"):text.rfind("}") + 1]).get("triggered", [])
            for idx in triggered:
                if 0 <= int(idx) < len(conditions):
                    candidates.append((f"recheck:{idx}", f"재검토 조건 발동 — \"{conditions[int(idx)]}\""))
        except Exception:  # noqa: BLE001
            logger.exception("recheck eval failed for %s", card["card_id"])

    # 중복 억제 후 기록
    fired: list[tuple[str, str]] = []
    for kind, message in candidates:
        recent = conn.execute(
            "SELECT 1 FROM card_alerts WHERE card_id = ? AND kind = ?"
            " AND created_at >= datetime('now', ?)",
            (card["card_id"], kind, f"-{ALERT_COOLDOWN_DAYS} days"),
        ).fetchone()
        if recent:
            continue
        conn.execute(
            "INSERT INTO card_alerts (card_id, kind, message) VALUES (?, ?, ?)",
            (card["card_id"], kind, message),
        )
        fired.append((kind, message))
    conn.commit()
    return fired


def _notify(router, card, messages: list[str]) -> None:
    body = (
        f"**{card['name']}** ({card['symbol']}) — 당신의 결정 카드 v{card['version']}에 변화가 있어요:\n"
        + "\n".join(f"- {m}" for m in messages)
        + f"\n\n다시 판단해 볼까요? → {WEB_BASE}/?card={card['card_id']}"
    )
    router.send(("cards", "signals"), f"🔄 결정 카드 재점검 — {card['name']}", body)


class _NullLLM:
    name = model = "null"

    def complete(self, system: str, user: str) -> str:
        raise RuntimeError("LLM not available")
