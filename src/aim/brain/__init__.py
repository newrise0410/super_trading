"""③ 두뇌 — P2에서 구현.

설계 (PLAN.md §3): TradingAgents(Apache 2.0) 토론 파이프라인 차용.
  애널리스트 4팀(기술·펀더멘털·뉴스·수급) → Bull vs Bear 토론 → 판정
  → decisions 테이블에 근거·확신도·토론 로그·데이터 스냅샷 구조화 저장.
딥씽킹(판정자)/퀵씽킹(애널리스트) 모델 분리. 검증된 MarketSnapshot만 입력(환각 방지).

참고 코드: references/TradingAgents/tradingagents/graph/, agents/
"""
