"""개인화 섹션 생성 (§10.6-2 — 마스터와 분리; 개인용 단계에선 사용자 1명).

P1에서는 빈 문자열. 이후: 관심종목 매칭 코멘트, 내 가상 포트폴리오 진단.
서비스화 시 이 함수가 사용자별 팬아웃 워커의 단위 작업이 된다.
"""

from __future__ import annotations

from typing import Any


def build_personal_section(user_context: dict[str, Any], master_md: str) -> str:
    # P1: 개인화 없음. P3+: 관심종목 교집합, 가상 포트폴리오 요약.
    return ""
