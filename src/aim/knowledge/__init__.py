"""종목 지식 저장소 — 분석 결과의 RAG식 캐시 (PLAN.md §13).

개념 검증: prism-insight cores/archive/ 인사이트 에이전트 (Mem0 스타일 종목 팩트,
AGPL — 개념 참고, 코드 미복사).

사용처:
- P2 두뇌: 분석 전 get_context(symbol)로 "이미 아는 것" 주입 → 델타만 새로 분석
- P4 Q&A: 자유질문 검색의 1차 소스 (FTS5 → P4에서 임베딩 리랭크 추가)
"""

from aim.knowledge.store import TTL_DAYS, KnowledgeStore

__all__ = ["KnowledgeStore", "TTL_DAYS"]
