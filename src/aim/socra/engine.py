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

# 내부 증거 키([tech.rsi14] 등) 누출 방지 — 프롬프트 규칙 + 서버측 이중 필터
_EVIDENCE_KEY_RE = re.compile(r"\s*\[[a-z][a-z0-9_]*\.[a-z0-9_]+\]")


def _clean_reply(text: str) -> str:
    return _EVIDENCE_KEY_RE.sub("", text).strip()
MIN_TURNS_PER_STAGE = 1   # LLM이 [[NEXT]] 신호를 줘도 최소 1답은 필요
MAX_TURNS_PER_STAGE = 4   # 신호가 없어도 강제 전진 (세션 늘어짐 방지)
_NEXT_MARKER_RE = re.compile(r"\s*\[\[NEXT\]\]\s*$")
STAGE_LABEL = {
    "business": "① 사업 이해", "valuation": "② 가격 vs 가치",
    "risk": "③ 리스크", "exit": "④ 출구 기준", "card": "결정 카드", "done": "완료",
    "recheck": "🔄 재점검",
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


def resolve_symbol(query: str, conn: "sqlite3.Connection | None" = None) -> tuple[str, str] | None:
    """자유 입력("삼성전자 살까?", "005930") → (종목코드, 표시명). 실패 시 None.

    우선순위: 6자리 코드 → 종목 마스터 DB(symbols, `aim symbols-sync`) → 인기종목 맵 폴백.
    """
    text = query.strip().lower()
    m = re.search(r"\b(\d{6})\b", text)
    if m:
        return m.group(1), m.group(1)
    if conn is not None:
        try:
            from aim.socra.symbols import search_symbol  # noqa: PLC0415

            hit = search_symbol(conn, text)
            if hit:
                return hit
        except Exception:  # noqa: BLE001
            logger.exception("symbol DB search failed")
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
        resolved = resolve_symbol(query, self._conn)
        if resolved is None:
            return {"error": "종목을 찾지 못했어요. 종목코드 6자리(예: 005930) 또는 종목명으로 입력해 주세요."}
        symbol, _ = resolved

        evidence_md, name, _snapshot = self._collect_evidence(symbol)
        self._auto_watchlist(symbol, name)

        session_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO socra_sessions (session_id, user_id, symbol, name, stage, evidence_md)"
            " VALUES (?, ?, ?, ?, 'business', ?)",
            (session_id, user_id, symbol, name, evidence_md),
        )
        self._conn.commit()

        opening = _clean_reply(self._quick.complete(
            prompts.OPENING_TEMPLATE.format(
                base=prompts.BASE_GUARD, stage_goal=prompts.STAGE_GOALS["business"],
                name=name, symbol=symbol, evidence=evidence_md,
            ),
            f"{name} 살까 말까 고민이에요.",
        ))
        self._save_turn(session_id, "bot", opening, "business")
        return {
            "session_id": session_id, "symbol": symbol, "name": name,
            "stage": "business", "stage_label": STAGE_LABEL["business"],
            "reply": opening, "legend": self._legend(opening, user_id),
        }

    # ── 턴 처리 ──────────────────────────────────────────────────

    def handle_message(self, session_id: str, text: str) -> dict[str, Any]:
        session = self._conn.execute(
            "SELECT * FROM socra_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session is None:
            return {"error": "세션을 찾을 수 없어요."}

        self._save_turn(session_id, "user", text, session["stage"])

        # 지식 모델: 용어 질문 감지 → asked 기록 (2층 신호)
        from aim.socra.mastery import MasteryModel  # noqa: PLC0415

        mastery = MasteryModel(self._conn, session["user_id"])
        mastery.detect_asked_concepts(text)

        if session["stage"] == "card":
            return self._handle_card_stage(session, text)
        if session["stage"] == "done":
            return self._reply(session, "이 세션은 완료됐어요. 사이드바에서 새 대화를 시작해 보세요! 🎉")

        # 일반 단계: 소크라테스 턴 (지식 상태 주입 — 난이도 적응)
        stage_goal = prompts.STAGE_GOALS[session["stage"]]
        if session["stage"] == "recheck" and session["ref_card_id"]:
            card = self._conn.execute(
                "SELECT target_price, stop_price FROM decision_cards WHERE card_id = ?",
                (session["ref_card_id"],),
            ).fetchone()
            if card:
                stage_goal = stage_goal.format(
                    target=card["target_price"] or "미설정", stop=card["stop_price"] or "미설정"
                )
        raw = self._quick.complete(
            prompts.TURN_TEMPLATE.format(
                base=prompts.BASE_GUARD,
                stage_goal=stage_goal,
                mastery=mastery.summary_text(),
                name=session["name"], symbol=session["symbol"],
                evidence=session["evidence_md"],
                history=self._history_text(session_id),
                user_text=text,
            ),
            text,
        )
        llm_next = bool(_NEXT_MARKER_RE.search(raw))
        reply = _clean_reply(_NEXT_MARKER_RE.sub("", raw))

        # 단계 진행: LLM [[NEXT]] 신호 (최소 1답) 또는 최대 답 수 도달 시 강제
        new_stage = session["stage"]
        user_turns = self._conn.execute(
            "SELECT COUNT(*) AS n FROM socra_turns WHERE session_id = ? AND role='user' AND stage = ?",
            (session_id, session["stage"]),
        ).fetchone()["n"]
        should_advance = (llm_next and user_turns >= MIN_TURNS_PER_STAGE) or (
            user_turns >= MAX_TURNS_PER_STAGE
        )
        if should_advance:
            if session["kind"] == "recheck" or session["stage"] == STAGES[-1]:
                return self._enter_card_stage(session, reply)  # 재질문은 재점검→카드 직행
            new_stage = STAGES[STAGES.index(session["stage"]) + 1]
            self._set_stage(session_id, new_stage)

        self._save_turn(session_id, "bot", reply, new_stage)
        return {
            "reply": reply, "legend": self._legend(reply, session["user_id"]),
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
            "reply": present, "legend": self._legend(present, session["user_id"]),
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
        concept_list = "\n".join(
            f"- {r['slug']}: {r['term']}"
            for r in self._conn.execute("SELECT slug, term FROM concepts")
        )
        raw = self._deep.complete(
            "너는 대화록 정리 서기다. 지시를 정확히 따르라.",
            prompts.CARD_SYNTH
            .replace("{transcript}", self._history_text(session["session_id"]))
            .replace("{concept_list}", concept_list),
        )
        try:
            text = re.sub(r"```(?:json)?|```", "", raw)
            start, end = text.find("{"), text.rfind("}")
            draft = json.loads(text[start:end + 1])
        except (ValueError, json.JSONDecodeError):
            logger.exception("card synth parse failed")
            return {"thesis": "(정리 실패 — 다시 시도해 주세요)", "gaps": ["카드 합성 실패"]}

        # 지식 모델 갱신 (deep 평가 신호): 이해 입증 → 3, 혼동 → 2
        from aim.socra.mastery import MasteryModel  # noqa: PLC0415

        mastery = MasteryModel(self._conn, session["user_id"])
        mastery.record_demonstrated(list(draft.get("concepts_understood") or []))
        for slug in draft.get("concepts_confused") or []:
            mastery.record_asked(slug)
        return draft

    def _save_card(self, session) -> str:
        draft = json.loads(session["card_draft_json"] or "{}")
        card_id = str(uuid.uuid4())
        # §4.5: 확정 시점의 근거를 구조화 동결 — 이후 diff의 기준점
        _md, _name, snapshot = self._collect_evidence(session["symbol"])
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
                json.dumps(snapshot or {"evidence_md": session["evidence_md"]}, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return card_id

    # ── 재질문 세션 (§4.5) ───────────────────────────────────────

    def start_requestion(self, card_id: str, alerts: list[str] | None = None) -> dict[str, Any]:
        """근거 변화 알림에서 진입 — 기존 카드를 배경으로 재점검 대화 시작."""
        card = self._conn.execute(
            "SELECT * FROM decision_cards WHERE card_id = ?", (card_id,)
        ).fetchone()
        if card is None:
            return {"error": "카드를 찾을 수 없어요."}

        # 알림 미지정 시 최근 알림 이력에서 로드
        if alerts is None:
            alerts = [r["message"] for r in self._conn.execute(
                "SELECT message FROM card_alerts WHERE card_id = ?"
                " ORDER BY created_at DESC LIMIT 5", (card_id,),
            )]

        evidence_md, name, _snap = self._collect_evidence(card["symbol"])
        session_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO socra_sessions"
            " (session_id, user_id, symbol, name, stage, evidence_md, kind, ref_card_id)"
            " VALUES (?, ?, ?, ?, 'recheck', ?, 'recheck', ?)",
            (session_id, card["user_id"], card["symbol"], name or card["name"],
             evidence_md, card_id),
        )
        self._conn.commit()

        stage_goal = prompts.STAGE_GOALS["recheck"].format(
            target=card["target_price"] or "미설정", stop=card["stop_price"] or "미설정",
        )
        opening = _clean_reply(self._quick.complete(
            prompts.REQUESTION_OPENING.format(
                base=prompts.BASE_GUARD, stage_goal=stage_goal,
                version=card["version"], created=card["created_at"][:10],
                thesis=card["thesis"],
                target=card["target_price"] or "미설정", stop=card["stop_price"] or "미설정",
                recheck=card["recheck_conditions"],
                alerts="\n".join(f"- {a}" for a in alerts) or "- (자동 감지 변화 없음 — 정기 재점검)",
                name=card["name"], symbol=card["symbol"], evidence=evidence_md,
            ),
            "알림 보고 왔어요.",
        ))
        self._save_turn(session_id, "bot", opening, "recheck")
        return {
            "session_id": session_id, "symbol": card["symbol"], "name": card["name"],
            "stage": "recheck", "stage_label": STAGE_LABEL["recheck"],
            "reply": opening, "legend": self._legend(opening, card["user_id"]),
        }

    # ── 내부 ─────────────────────────────────────────────────────

    def _collect_evidence(self, symbol: str) -> tuple[str, str, dict[str, Any]]:
        """증거 수집 (기술·수급 + KIS 밸류에이션) → (md, 이름, 구조화 스냅샷).

        스냅샷은 §4.5 근거 diff의 기준점 — 카드 저장 시 동결된다.
        실패해도 세션은 시작된다.
        """
        evidence_md, name = "", symbol
        snapshot: dict[str, Any] = {}
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
            snapshot = {
                "as_of": ev.as_of, "price": ev.price,
                "items": [
                    {"key": i.key, "label": i.label, "value": i.value, "unit": i.unit,
                     "direction": i.direction, "detail": i.detail}
                    for i in ev.items
                ],
            }
        except Exception:  # noqa: BLE001
            logger.exception("evidence collection failed for %s", symbol)
            evidence_md = "(증거 수집 실패 — 수치 인용 없이 개념 중심으로 진행)"
        return evidence_md, name, snapshot

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

    def _legend(self, reply: str, user_id: str) -> list[dict]:
        """범례 — 이해 입증(레벨 3) 개념은 생략, 노출된 것은 exposure 기록 (성장 가시화)."""
        from aim.socra.mastery import MasteryModel  # noqa: PLC0415

        mastery = MasteryModel(self._conn, user_id)
        known = mastery.known_slugs()
        legend = [item for item in detect_terms(self._conn, reply) if item["slug"] not in known]
        mastery.record_exposure([item["slug"] for item in legend])
        return legend

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
