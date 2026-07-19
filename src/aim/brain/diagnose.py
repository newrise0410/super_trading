"""AI 포트폴리오 진단 — 보유 관점 리포트 (딥씽킹 티어).

규제 유의(§10.4): 매수/매도 지시가 아닌 '점검 관점' 프레임 + 면책 고지.
"""

from __future__ import annotations

import logging
import sqlite3

from aim.llm.base import LLMClient
from aim.portfolio import PriceLookup, render_portfolio_md, value_portfolio
from aim.storage.repositories.portfolio import PortfolioRepository
from aim.storage.repositories.reports import ReportsRepository

logger = logging.getLogger(__name__)

DIAG_SYS = """당신은 포트폴리오 리스크 분석가다. 아래 사용자의 실제 포트폴리오 평가를 읽고 진단 리포트를 작성하라.

형식 (한국어 마크다운):
### 구성 요약 — 자산·통화·섹터 구성의 특징 2~3줄
### 집중 리스크 — 비중 쏠림, 상관관계 높은 종목군(예: 반도체 계열 합산 비중), 단일 테마 노출
### 시장 환경 유의점 — 제공된 등락률에서 읽히는 최근 흐름과 포트폴리오의 민감도
### 점검 포인트 — 사용자가 스스로 확인해볼 질문 3~5개 (지시가 아닌 점검 관점)

규칙: 제공된 수치만 인용(외부 수치 창작 금지). 매수/매도 지시 표현 금지 — "점검해볼 만하다" 프레임.
마지막 줄에 "본 진단은 정보 제공 목적이며 투자 자문이 아닙니다." 명시."""


def diagnose_portfolio(
    conn: sqlite3.Connection,
    deep: LLMClient,
    lookup: PriceLookup,
    fx_usdkrw: float | None = None,
) -> str | None:
    """진단 리포트 마크다운 반환 (포트폴리오 없으면 None). reports에 저장."""
    rows = PortfolioRepository(conn).list_all()
    if not rows:
        return None

    views, totals = value_portfolio(rows, lookup, fx_usdkrw)
    port_md = render_portfolio_md(views, totals)

    diag = deep.complete(DIAG_SYS, port_md)
    full = f"{port_md}\n\n## 🩺 AI 진단\n{diag}"

    ReportsRepository(conn).save(kind="portfolio_diag", market="ALL", master_md=full, data={})
    return full
