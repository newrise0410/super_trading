"""증거 레이어 — 상승/하락 근거 데이터의 수집·구조화 (PLAN.md 근거 설계).

원칙:
1. LLM은 이 번들 밖의 수치를 인용할 수 없다 (환각 방지 — TradingAgents 검증 스냅샷 패턴)
2. 파생지표(RSI, 연속일수, z-score)는 전부 코드가 계산 — LLM은 해석만
3. 모든 EvidenceItem은 key로 인용 가능 → decisions.rationale_json → /why 재현
"""

from aim.evidence.models import EvidenceItem, StockEvidence

__all__ = ["EvidenceItem", "StockEvidence"]
