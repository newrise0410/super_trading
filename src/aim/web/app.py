"""웹 대시보드 (P5) — FastAPI + 자체 포함 단일 페이지 (빌드 도구·CDN 불필요).

데이터 함수(순수, conn→dict)와 라우트(얇은 래퍼)를 분리 — 테스트는 데이터 함수만.
서비스화 시 이 API가 §10.2 서비스 API의 시드가 된다.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from aim.config import Settings

_PAGE_PATH = Path(__file__).parent / "dashboard.html"


# ── 데이터 함수 (순수) ────────────────────────────────────────────


def overview_data(conn: sqlite3.Connection, lookup, fx: float | None) -> dict:
    from dataclasses import asdict  # noqa: PLC0415

    from aim.portfolio import value_portfolio  # noqa: PLC0415
    from aim.storage.repositories.portfolio import PortfolioRepository  # noqa: PLC0415

    rows = PortfolioRepository(conn).list_all()
    views, totals = value_portfolio(rows, lookup, fx)
    return {"positions": [asdict(v) for v in views], "totals": totals}


def equity_data(conn: sqlite3.Connection) -> dict:
    """전략별 자산곡선 — 수익률(%)로 지수화 (공통 축, §dataviz 단일 축 원칙)."""
    labels = {"benchmark": "벤치마크(K200)", "momentum": "모멘텀", "ai_debate": "AI 토론"}
    series = []
    for pf in conn.execute("SELECT * FROM virtual_portfolios ORDER BY strategy"):
        points = [
            [r["date"], round((r["value"] / pf["initial_cash"] - 1) * 100, 3)]
            for r in conn.execute(
                "SELECT date, value FROM sim_equity WHERE portfolio_id = ? ORDER BY date",
                (pf["id"],),
            )
        ]
        if points:
            series.append({
                "key": pf["strategy"],
                "label": labels.get(pf["strategy"], pf["strategy"]),
                "points": points,
            })
    return {"series": series}


def decisions_data(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT created_at, symbol, name, action, confidence, outcome_return_5d"
        " FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,),
    )]


def reports_list(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT report_id, kind, created_at FROM reports ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )]


def report_detail(conn: sqlite3.Connection, report_id: str) -> dict | None:
    row = conn.execute(
        "SELECT report_id, kind, created_at, master_md FROM reports WHERE report_id = ?",
        (report_id,),
    ).fetchone()
    return dict(row) if row else None


def signals_data(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT fired_at, symbol, kind, severity, message FROM signals"
        " ORDER BY fired_at DESC LIMIT ?", (limit,),
    )]


# ── FastAPI 앱 ───────────────────────────────────────────────────


def create_app(settings: Settings):
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.responses import HTMLResponse, JSONResponse  # noqa: PLC0415

    from aim.storage import db  # noqa: PLC0415

    app = FastAPI(title="AIM Dashboard")

    def _conn() -> sqlite3.Connection:
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        return conn

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return _PAGE_PATH.read_text(encoding="utf-8")

    @app.get("/api/overview")
    def overview():
        from aim.portfolio.prices import kr_lookup_for, make_lookup, usdkrw  # noqa: PLC0415

        conn = _conn()
        try:
            return overview_data(conn, make_lookup(kr_lookup_for(settings, conn)), usdkrw())
        finally:
            conn.close()

    @app.get("/api/equity")
    def equity():
        conn = _conn()
        try:
            return equity_data(conn)
        finally:
            conn.close()

    @app.get("/api/decisions")
    def decisions():
        conn = _conn()
        try:
            return decisions_data(conn)
        finally:
            conn.close()

    @app.get("/api/reports")
    def reports():
        conn = _conn()
        try:
            return reports_list(conn)
        finally:
            conn.close()

    @app.get("/api/reports/{report_id}")
    def report(report_id: str):
        conn = _conn()
        try:
            data = report_detail(conn, report_id)
        finally:
            conn.close()
        if data is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return data

    @app.get("/api/signals")
    def signals():
        conn = _conn()
        try:
            return signals_data(conn)
        finally:
            conn.close()

    return app


def run_dashboard(settings: Settings, port: int = 8501) -> None:
    import uvicorn  # noqa: PLC0415

    print(f"대시보드: http://localhost:{port} (Ctrl+C 종료)")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
