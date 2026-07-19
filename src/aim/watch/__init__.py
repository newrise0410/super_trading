"""관심종목 실시간 추적 + 룰 기반 시그널 (PLAN.md §14).

구조:
  tracker.py   — 상주 폴링 루프 (aim watch). 시그널 발생 → 알림 + DB + knowledge 기록
  signals.py   — 룰 정의 (100% 코드, LLM 없음 = 비용 제로·무지연)
  baseline.py  — 시간대 정규화: 동시각 누적거래량 프로파일 (오탐 방지의 핵심)
  cooldown.py  — 같은 (종목, 시그널) 재알림 억제
  provider.py  — IntradayProvider/DisclosureProvider 프로토콜 + Mock (KIS/DART는 ②③ 단계)

시그널 감지는 룰, 해석 코멘트만 LLM(P2+, 시그널 발생 시 1회) — prism-insight 트리거 개념.
"""
