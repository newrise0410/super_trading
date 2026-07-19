"""사용자 지식 모델 (S2) — 개념 숙련도 추적.

신호 → 레벨:
- 범례 노출: 0→1 (exposures 카운트) — 반복 노출은 자연 학습의 증거
- 용어 질문 ("PER이 뭐야?"): →2 (질문 = 아직 모름. 레벨 3이었어도 강등 — 정직한 모델)
- 세션 종료 deep 평가에서 이해 입증: →3 (이후 범례에서 생략 = 성장의 가시화)
"""

from __future__ import annotations

import re
import sqlite3

LEVEL_UNKNOWN, LEVEL_EXPOSED, LEVEL_ASKED, LEVEL_DEMONSTRATED = 0, 1, 2, 3

# "~가 뭐야/무슨 뜻/모르겠" 류 — 용어 질문 감지
_ASK_PATTERN = re.compile(r"(뭐야|뭐예요|뭐죠|무슨\s*뜻|모르겠|어떤\s*의미|설명해)")


class MasteryModel:
    def __init__(self, conn: sqlite3.Connection, user_id: str = "local") -> None:
        self._conn = conn
        self._user = user_id

    # ── 신호 기록 ────────────────────────────────────────────────

    def record_exposure(self, slugs: list[str]) -> None:
        for slug in slugs:
            self._conn.execute(
                "INSERT INTO concept_mastery (user_id, slug, level, exposures) VALUES (?, ?, 1, 1)"
                " ON CONFLICT(user_id, slug) DO UPDATE SET"
                " level = MAX(level, 1), exposures = exposures + 1, updated_at = datetime('now')",
                (self._user, slug),
            )
        self._conn.commit()

    def record_asked(self, slug: str) -> None:
        self._conn.execute(
            "INSERT INTO concept_mastery (user_id, slug, level) VALUES (?, ?, 2)"
            " ON CONFLICT(user_id, slug) DO UPDATE SET level = 2, updated_at = datetime('now')",
            (self._user, slug),
        )
        self._conn.commit()

    def record_demonstrated(self, slugs: list[str]) -> None:
        for slug in slugs:
            self._conn.execute(
                "INSERT INTO concept_mastery (user_id, slug, level) VALUES (?, ?, 3)"
                " ON CONFLICT(user_id, slug) DO UPDATE SET level = 3, updated_at = datetime('now')",
                (self._user, slug),
            )
        self._conn.commit()

    def detect_asked_concepts(self, user_text: str) -> list[str]:
        """사용자 발화에서 '용어 질문' 감지 → 해당 개념 slug 목록 + asked 기록."""
        if not _ASK_PATTERN.search(user_text):
            return []
        from aim.socra.concepts import detect_terms  # noqa: PLC0415

        asked = [item["slug"] for item in detect_terms(self._conn, user_text)]
        for slug in asked:
            self.record_asked(slug)
        return asked

    # ── 조회 ─────────────────────────────────────────────────────

    def known_slugs(self) -> set[str]:
        """레벨 3(이해 입증) — 범례 생략 대상."""
        return {
            row["slug"] for row in self._conn.execute(
                "SELECT slug FROM concept_mastery WHERE user_id = ? AND level >= 3", (self._user,)
            )
        }

    def summary_text(self) -> str:
        """프롬프트 주입용 지식 상태 요약."""
        rows = self._conn.execute(
            "SELECT m.level, c.term FROM concept_mastery m JOIN concepts c ON c.slug = m.slug"
            " WHERE m.user_id = ? AND m.level >= 2 ORDER BY m.level DESC", (self._user,),
        ).fetchall()
        known = [r["term"] for r in rows if r["level"] >= 3]
        weak = [r["term"] for r in rows if r["level"] == 2]
        parts = []
        if known:
            parts.append(f"이해한 개념(설명 없이 사용 가능): {', '.join(known[:10])}")
        if weak:
            parts.append(f"미숙련 개념(쉬운 말로 풀어서): {', '.join(weak[:10])}")
        return " / ".join(parts) if parts else "아직 파악된 지식 상태 없음 — 최대한 쉬운 말로"
