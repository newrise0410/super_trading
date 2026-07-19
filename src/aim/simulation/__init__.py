"""② 전략 시뮬레이션 — P3에서 구현.

설계 (PLAN.md §5, §12-1): 전략별 독립 가상 포트폴리오 병렬 운용.
  모든 거래는 decisions.decision_id에 연결 → 완전 감사 추적 (Fincept Alpha Arena 개념).
  슬롯 최대 10, 종목당 10%, 섹터 최대 3종목.
스키마: virtual_portfolios / virtual_positions / virtual_trades (001_init.sql에 선정의).

참고 코드: references/Vibe-Trading/agent/backtest/ (MIT),
          references/FinceptTerminal/docs/ALPHA_ARENA.md (개념만, AGPL)
"""
