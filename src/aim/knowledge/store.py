"""KnowledgeStore — 종목별 팩트의 저장·대체·시효 관리·검색.

원칙 (PLAN.md §13):
1. 비싼 추론(LLM 분석)만 캐시. 시세·수급 원본은 data/에서 항상 라이브 조회
2. 팩트 유형별 TTL — 만료된 팩트는 기본 제외 (요청 시 stale 표시로 포함 가능)
3. 같은 (symbol, fact_type, topic)은 최신 팩트가 이전 것을 대체(supersede) — 삭제 대신 이력 보존
4. 모든 팩트는 as_of(기준 시점)와 출처(report/decision)를 가진다 — LLM에 신선도가 항상 노출됨
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, timedelta

from aim.storage.repositories.base import BaseRepository

# 팩트 유형별 유효기간 (일). None = 무기한 (outcome: 판단 결과 이력은 영구 보존)
TTL_DAYS: dict[str, int | None] = {
    "profile": 365,      # 기업 개요·상장 정보
    "business": 180,     # 사업 구조·경쟁 구도
    "financials": 120,   # 재무·실적 (분기 주기)
    "risk": 90,          # 리스크 요인
    "thesis": 60,        # 투자 논지
    "catalyst": 30,      # 촉매·이벤트
    "technicals": 5,     # 기술적 지표 해석
    "flow": 3,           # 수급 해석
    "outcome": None,     # 과거 판단과 실현 결과 (캘리브레이션 원천)
}


class KnowledgeStore(BaseRepository):
    def upsert_fact(
        self,
        *,
        market: str,
        symbol: str,
        fact_type: str,
        content: str,
        topic: str = "",
        as_of: str | None = None,
        confidence: float | None = None,
        source_report_id: str | None = None,
        source_decision_id: str | None = None,
    ) -> str:
        """팩트 저장. 같은 (symbol, fact_type, topic)의 활성 팩트는 이 팩트로 대체된다."""
        if fact_type not in TTL_DAYS:
            raise ValueError(f"unknown fact_type: {fact_type} (allowed: {sorted(TTL_DAYS)})")

        as_of = as_of or date.today().isoformat()
        ttl = TTL_DAYS[fact_type]
        valid_until = (
            (date.fromisoformat(as_of) + timedelta(days=ttl)).isoformat() if ttl else None
        )
        fact_id = str(uuid.uuid4())

        self.conn.execute(
            "UPDATE stock_facts SET superseded_by = ? "
            "WHERE symbol = ? AND fact_type = ? AND topic = ? AND superseded_by IS NULL",
            (fact_id, symbol, fact_type, topic),
        )
        self.conn.execute(
            """
            INSERT INTO stock_facts (
                fact_id, market, symbol, fact_type, topic, content,
                as_of, valid_until, confidence, source_report_id, source_decision_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id, market, symbol, fact_type, topic, content,
                as_of, valid_until, confidence, source_report_id, source_decision_id,
            ),
        )
        self.conn.commit()
        return fact_id

    def get_context(
        self, symbol: str, *, include_stale: bool = False, limit: int = 30
    ) -> list[sqlite3.Row]:
        """종목의 활성(최신·유효) 팩트 묶음 — 분석/Q&A 전 컨텍스트 주입용."""
        stale_filter = "" if include_stale else "AND (valid_until IS NULL OR valid_until >= date('now'))"
        cur = self.conn.execute(
            f"""
            SELECT * FROM stock_facts
            WHERE symbol = ? AND superseded_by IS NULL {stale_filter}
            ORDER BY fact_type, as_of DESC
            LIMIT ?
            """,
            (symbol, limit),
        )
        return cur.fetchall()

    def search(self, query: str, *, symbol: str | None = None, limit: int = 10) -> list[sqlite3.Row]:
        """FTS5 전문검색 (P4에서 임베딩 리랭크 추가 예정).

        참고: FTS5 기본 토크나이저는 한국어 형태소 미지원 — 정확 어형 매칭만.
        v1 한계로 수용, P4 임베딩 도입 시 리콜 보완.
        """
        symbol_filter = "AND f.symbol = ?" if symbol else ""
        params: list = [query]
        if symbol:
            params.append(symbol)
        params.append(limit)
        cur = self.conn.execute(
            f"""
            SELECT f.*, rank FROM stock_facts_fts
            JOIN stock_facts f ON f.id = stock_facts_fts.rowid
            WHERE stock_facts_fts MATCH ?
              AND f.superseded_by IS NULL
              {symbol_filter}
            ORDER BY rank
            LIMIT ?
            """,
            params,
        )
        return cur.fetchall()

    @staticmethod
    def render_context(rows: list[sqlite3.Row]) -> str:
        """팩트를 LLM 프롬프트용 마크다운으로 — 신선도(as_of)가 항상 보이게."""
        if not rows:
            return "(이 종목에 대해 저장된 지식 없음 — 전체 신규 분석 필요)"
        lines = []
        for r in rows:
            staleness = f", 유효기한 {r['valid_until']}" if r["valid_until"] else ""
            lines.append(f"- [{r['fact_type']}] ({r['as_of']} 기준{staleness}) {r['content']}")
        return "\n".join(lines)
