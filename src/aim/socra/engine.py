"""소크라 대화 엔진 v1 — 세션 상태 머신 + 턴 처리 + 카드 합성 (PLAN §4).

단계: business → valuation → risk → exit → card → done
- 단계 진행: 단계당 사용자 답 2회 후 다음 단계 (v1 단순 규칙 — S2에서 LLM 판단으로 고도화)
- 범례(1층): 봇 응답의 용어를 concepts에서 감지해 별도 필드로 반환 (UI가 하단 렌더)
- 카드: exit 완료 → deep 모델이 대화 전문에서 사용자의 말만으로 초안 합성 → "확정" 시 저장
  (근거 스냅샷 동결 — §4.5 재질문 루프의 기준점)
- 세션 시작 시 자동 관심종목 등록
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from typing import Any

from aim.config import Settings
from aim.llm.base import LLMClient
from aim.socra import prompts
from aim.socra.concepts import detect_terms

logger = logging.getLogger(__name__)

STAGES = ["business", "valuation", "risk", "exit"]
TURNS_PER_STAGE = 2
STAGE_LABEL = {
    "business": "① 사업 이해", "valuation": "② 가격 vs 가치",
    "risk": "③ 리스크", "exit": "④ 출구 기준", "card": "결정 카드", "done": "완료",
}

# 초보 진입 장벽 완화용 — 인기 종목 이름→코드 (S2에서 검색 API로 대체)
NAME_MAP = {
    "삼성전자": "005930", "sk하이닉스": "000660", "하이닉스": "000660",
    "lg에너지솔루션": "373220", "네이버": "035420", "naver": "035420",
    "카카오": "035720", "현대차": "005380", "기아": "000270",
    "삼성바이오로직스": "207940", "셀트리온": "068270", "포스코홀딩스": "005490",
    "삼성sdi": "006400", "lg화학": "051910", "kb금융": "105560", "신한지주": "055550",
    "한화에어로스페이스": "012450", "hd현대중공업": "329180", "두산에너빌리티": "034020",
}


def resolve_symbol(query: str) -> tuple[str, str] | None:
    """자유 입력("삼성전자 살까?", "005930") → (종목코드, 표시명). 실패 시 None."""
    text = query.strip().lower()
    m = re.search(r"\b(\d{6})\b", text)
    if m:
        return m.group(1), m.group(1)
    for name, code in NAME_MAP.items():
        if name in text:
            return code, name if not name.islower() else name.upper()
    return None


class SocraEngine:
    def __init__(
        self, conn: sqlite3.Connection, settings: Settings,
        quick: LLMClient, deep: LLMClient,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._quick = quick
        self._deep = deep

    # ── 세션 시작 ────────────────────────────────────────────────

    def start_session(self, query: str, user_id: str = "local") -> dict[str, Any]:
        resolved = resolve_symbol(query)
        if resolved is None:
            return {"error": "종목을 찾지 못했어요. 종목코드 6자리(예: 005930) 또는 종목명으로 입력해 주세요."}
        symbol, _ = resolved

        evidence_md, name = self._collect_evidence(symbol)
        self._auto_watchlist(symbol, name)

        session_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO socra_sessions (session_id, user_id, symbol, name, stage, evidence_md)"
            " VALUES (?, ?, ?, ?, 'business', ?)",
            (session_id, user_id, symbol, name, evidence_md),
        )
        self._conn.commit()

        opening = self._quick.complete(
            prompts.OPENING_TEMPLATE.format(
                base=prompts.BASE_GUARD, stage_goal=prompts.STAGE_GOALS["business"],
                name=name, symbol=symbol, evidence=evidence_md,
            ),
            f"{name} 살까 말까 고민이에요.",
        )
        self._save_turn(session_id, "bot", opening, "business")
        return {
            "session_id": session_id, "symbol": symbol, "name": name,
            "stage": "business", "stage_label": STAGE_LABEL["business"],
            "reply": opening, "legend": detect_terms(self._conn, opening),
        }

    # ── 턴 처리 ──────────────────────────────────────────────────

    def handle_message(self, session_id: str, text: str) -> dict[str, Any]:
        session = self._conn.execute(
            "SELECT * FROM socra_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session is None:
            return {"error": "세션을 찾을 수 없어요."}

        self._save_turn(session_id, "user", text, session["stage"])

        if session["stage"] == "card":
            return self._handle_card_stage(session, text)
        if session["stage"] == "done":
            return self._reply(session, "이 세션은 완료됐어요. 사이드바에서 새 대화를 시작해 보세요! 🎉")

        # 일반 단계: 소크라테스 턴
        reply = self._quick.complete(
            prompts.TURN_TEMPLATE.format(
                base=prompts.BASE_GUARD,
                stage_goal=prompts.STAGE_GOALS[session["stage"]],
                name=session["name"], symbol=session["symbol"],
                evidence=session["evidence_md"],
                history=self._history_text(session_id),
                user_text=text,
            ),
            text,
        )

        # 단계 진행 판정 (v1: 단계당 사용자 답 N회)
        new_stage = session["stage"]
        user_turns = self._conn.execute(
            "SELECT COUNT(*) AS n FROM socra_turns WHERE session_id = ? AND role='user' AND stage = ?",
            (session_id, session["stage"]),
        ).fetchone()["n"]
        if user_turns >= TURNS_PER_STAGE:
            idx = STAGES.index(session["stage"])
            if idx + 1 < len(STAGES):
                new_stage = STAGES[idx + 1]
            else:
                return self._enter_card_stage(session, reply)
            self._set_stage(session_id, new_stage)

        self._save_turn(session_id, "bot", reply, new_stage)
        return {
            "reply": reply, "legend": detect_terms(self._conn, reply),
            "stage": new_stage, "stage_label": STAGE_LABEL[new_stage],
        }

    # ── 카드 단계 ────────────────────────────────────────────────

    def _enter_card_stage(self, session, last_reply: str) -> dict[str, Any]:
        draft = self._synthesize_card(session)
        gaps = draft.get("gaps") or []
        gaps_line = (
            "아직 채워지지 않은 부분: " + " / ".join(gaps) if gaps
            else "네 단계가 모두 채워졌어요. 👏"
        )
        present = last_reply + "\n\n" + prompts.CARD_PRESENT.format(gaps_line=gaps_line)

        self._conn.execute(
            "UPDATE socra_sessions SET stage='card', card_draft_json=?, updated_at=datetime('now')"
            " WHERE session_id = ?",
            (json.dumps(draft, ensure_ascii=False), session["session_id"]),
        )
        self._conn.commit()
        self._save_turn(session["session_id"], "bot", present, "card")
        return {
            "reply": present, "legend": detect_terms(self._conn, present),
            "stage": "card", "stage_label": STAGE_LABEL["card"], "card_draft": draft,
        }

    def _handle_card_stage(self, session, text: str) -> dict[str, Any]:
        if "확정" in text.strip():
            card_id = self._save_card(session)
            self._set_stage(session["session_id"], "done")
            reply = (
                f"결정 카드가 저장됐어요. 📌\n\n이제부터 **{session['name']}**의 가격과 "
                "카드의 근거들을 지켜보다가, 당신이 세운 기준에 닿거나 근거가 크게 변하면 알려드릴게요.\n"
                "오늘 세운 기준은 시장이 시험해 줄 거예요 — 그때 또 같이 생각해요."
            )
            self._save_turn(session["session_id"], "bot", reply, "done")
            return {"reply": reply, "legend": [], "stage": "done",
                    "stage_label": STAGE_LABEL["done"], "card_id": card_id}

        # 수정 요청 → 대화 반영해 초안 재합성
        draft = self._synthesize_card(session)
        self._conn.execute(
            "UPDATE socra_sessions SET card_draft_json=?, updated_at=datetime('now') WHERE session_id=?",
            (json.dumps(draft, ensure_ascii=False), session["session_id"]),
        )
        self._conn.commit()
        reply = "말씀 반영해서 카드를 다시 정리했어요. 오른쪽 카드를 확인하시고, 좋으면 \"확정\"이라고 해주세요."
        self._save_turn(session["session_id"], "bot", reply, "card")
        return {"reply": reply, "legend": [], "stage": "card",
                "stage_label": STAGE_LABEL["card"], "card_draft": draft}

    def _synthesize_card(self, session) -> dict[str, Any]:
        raw = self._deep.complete(
            "너는 대화록 정리 서기다. 지시를 정확히 따르라.",
            prompts.CARD_SYNTH.replace("{transcript}", self._history_text(session["session_id"])),
        )
        try:
            text = re.sub(r"```(?:json)?|```", "", raw)
            start, end = text.find("{"), text.rfind("}")
            return json.loads(text[start:end + 1])
        except (ValueError, json.JSONDecodeError):
            logger.exception("card synth parse failed")
            return {"thesis": "(정리 실패 — 다시 시도해 주세요)", "gaps": ["카드 합성 실패"]}

    def _save_card(self, session) -> str:
        draft = json.loads(session["card_draft_json"] or "{}")
        card_id = str(uuid.uuid4())
        # 기존 활성 카드 supersede (§4.5 버전 이력)
        prev = self._conn.execute(
            "SELECT card_id, version FROM decision_cards"
            " WHERE user_id=? AND symbol=? AND status='active'",
            (session["user_id"], session["symbol"]),
        ).fetchone()
        version = (prev["version"] + 1) if prev else 1
        if prev:
            self._conn.execute(
                "UPDATE decision_cards SET status='superseded', superseded_by=? WHERE card_id=?",
                (card_id, prev["card_id"]),
            )
        self._conn.execute(
            "INSERT INTO decision_cards (card_id, session_id, user_id, symbol, name, version,"
            " thesis, target_price, target_reason, stop_price, stop_reason, recheck_conditions,"
            " confidence_self, evidence_snapshot_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                card_id, session["session_id"], session["user_id"], session["symbol"],
                session["name"], version,
                draft.get("thesis", ""),
                draft.get("target_price"), draft.get("target_reason"),
                draft.get("stop_price"), draft.get("stop_reason"),
                json.dumps(draft.get("recheck_conditions", []), ensure_ascii=False),
                draft.get("confidence_self"),
                json.dumps({"evidence_md": session["evidence_md"]}, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return card_id

    # ── 내부 ─────────────────────────────────────────────────────

    def _collect_evidence(self, symbol: str) -> tuple[str, str]:
        """증거 수집 (기술·수급 + KIS 밸류에이션). 실패해도 세션은 시작된다."""
        evidence_md, name = "", symbol
        try:
            from aim.evidence.collector import collect_kr_evidence  # noqa: PLC0415

            ev = collect_kr_evidence(symbol)
            name = ev.name
            # 밸류에이션 축 — KIS 현재가의 PER/PBR
            if self._settings.kis_app_key:
                try:
                    from aim.data.kis.auth import KISAuth  # noqa: PLC0415
                    from aim.data.kis.intraday import KISIntradayProvider  # noqa: PLC0415
                    from aim.evidence.models import EvidenceItem  # noqa: PLC0415

                    auth = KISAuth(
                        self._settings.kis_app_key, self._settings.kis_app_secret,
                        self._settings.kis_env,
                    )
                    quotes = KISIntradayProvider(self._conn, auth).snapshot([symbol])
                    if quotes and quotes[0].per:
                        ev.items.append(EvidenceItem(
                            "val.per", "fundamental", "PER", quotes[0].per, "배",
                            detail="주가 ÷ 주당 1년 이익",
                        ))
                    if quotes and quotes[0].pbr:
                        ev.items.append(EvidenceItem(
                            "val.pbr", "fundamental", "PBR", quotes[0].pbr, "배",
                            detail="주가 ÷ 주당 순자산",
                        ))
                except Exception:  # noqa: BLE001
                    logger.exception("valuation evidence failed")
            evidence_md = ev.render_for_llm()
        except Exception:  # noqa: BLE001
            logger.exception("evidence collection failed for %s", symbol)
            evidence_md = "(증거 수집 실패 — 수치 인용 없이 개념 중심으로 진행)"
        return evidence_md, name

    def _auto_watchlist(self, symbol: str, name: str) -> None:
        try:
            from aim.storage.repositories.watch import WatchlistRepository  # noqa: PLC0415

            WatchlistRepository(self._conn).add(symbol, name, "KR")
        except Exception:  # noqa: BLE001
            logger.exception("auto watchlist failed")

    def _history_text(self, session_id: str, limit: int = 40) -> str:
        rows = self._conn.execute(
            "SELECT role, content FROM socra_turns WHERE session_id = ? ORDER BY id LIMIT ?",
            (session_id, limit),
        ).fetchall()
        who = {"bot": "소크라", "user": "사용자"}
        return "\n".join(f"{who[r['role']]}: {r['content']}" for r in rows)

    def _save_turn(self, session_id: str, role: str, content: str, stage: str) -> None:
        self._conn.execute(
            "INSERT INTO socra_turns (session_id, role, content, stage) VALUES (?, ?, ?, ?)",
            (session_id, role, content, stage),
        )
        self._conn.execute(
            "UPDATE socra_sessions SET updated_at=datetime('now') WHERE session_id=?", (session_id,)
        )
        self._conn.commit()

    def _set_stage(self, session_id: str, stage: str) -> None:
        self._conn.execute(
            "UPDATE socra_sessions SET stage=?, updated_at=datetime('now') WHERE session_id=?",
            (stage, session_id),
        )
        self._conn.commit()

    def _reply(self, session, text: str) -> dict[str, Any]:
        return {"reply": text, "legend": [], "stage": session["stage"],
                "stage_label": STAGE_LABEL.get(session["stage"], session["stage"])}
