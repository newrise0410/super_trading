"""웹 대시보드 (P5) — FastAPI + 자체 포함 단일 페이지 (빌드 도구·CDN 불필요).

데이터 함수(순수, conn→dict)와 라우트(얇은 래퍼)를 분리 — 테스트는 데이터 함수만.
서비스화 시 이 API가 §10.2 서비스 API의 시드가 된다.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from aim.config import Settings

_DASH_PATH = Path(__file__).parent / "dashboard.html"
_SOCRA_PATH = Path(__file__).parent / "socra.html"


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


def market_summary(settings: Settings, conn: sqlite3.Connection) -> dict:
    """첫 화면 증시현황 — KR(KIS) + US(yfinance) + 환율. 실패 축 격리."""
    kr: list[list] = []
    if settings.kis_app_key and settings.kis_app_secret:
        try:
            from aim.data.kis.auth import KISAuth  # noqa: PLC0415
            from aim.data.kis.market import KISMarketProvider  # noqa: PLC0415

            provider = KISMarketProvider(
                conn, KISAuth(settings.kis_app_key, settings.kis_app_secret, settings.kis_env)
            )
            kr = [list(q) for q in provider.index_quotes()]
        except Exception:  # noqa: BLE001
            pass
    try:
        from aim.reports.us import fetch_us_indices  # noqa: PLC0415

        us = [list(q) for q in fetch_us_indices()[:2]]  # S&P500·NASDAQ만 (첫 화면 간결)
    except Exception:  # noqa: BLE001
        us = []
    try:
        from aim.portfolio.prices import usdkrw  # noqa: PLC0415

        fx = usdkrw()
    except Exception:  # noqa: BLE001
        fx = None
    return {"kr": kr, "us": us, "usdkrw": fx}


def socra_sessions_list(conn: sqlite3.Connection, user_id: str = "local") -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT session_id, symbol, name, stage, updated_at FROM socra_sessions"
        " WHERE user_id = ? ORDER BY updated_at DESC LIMIT 50", (user_id,),
    )]


def socra_session_detail(conn: sqlite3.Connection, session_id: str) -> dict | None:
    session = conn.execute(
        "SELECT * FROM socra_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if session is None:
        return None
    turns = [dict(r) for r in conn.execute(
        "SELECT role, content, stage, created_at FROM socra_turns"
        " WHERE session_id = ? ORDER BY id", (session_id,),
    )]
    card = conn.execute(
        "SELECT * FROM decision_cards WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return {
        "session": dict(session),
        "turns": turns,
        "card_draft": json.loads(session["card_draft_json"]) if session["card_draft_json"] else None,
        "card": dict(card) if card else None,
    }


# ── FastAPI 앱 ───────────────────────────────────────────────────


def create_app(settings: Settings):
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.responses import HTMLResponse, JSONResponse  # noqa: PLC0415

    from aim.storage import db  # noqa: PLC0415

    from fastapi import Body  # noqa: PLC0415

    from aim.llm import build_llm  # noqa: PLC0415
    from aim.socra.concepts import seed_concepts  # noqa: PLC0415
    from aim.socra.engine import SocraEngine  # noqa: PLC0415

    app = FastAPI(title="SOCRA")

    def _conn() -> sqlite3.Connection:
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        return conn

    # 개념 사전 시드 (멱등) + LLM 클라이언트 (재사용)
    _c = _conn()
    seed_concepts(_c)
    _c.close()
    try:
        quick_llm = build_llm(settings, "quick")
        deep_llm = build_llm(settings, "deep")
    except RuntimeError:  # LLM 미설정 — 대시보드만 동작
        quick_llm = deep_llm = None

    @app.get("/", response_class=HTMLResponse)
    def socra_page() -> str:
        return _SOCRA_PATH.read_text(encoding="utf-8")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dash_page() -> str:
        return _DASH_PATH.read_text(encoding="utf-8")

    _mkt_cache: dict = {"at": 0.0, "data": None}

    @app.get("/api/market/summary")
    def market_sum():
        import time as time_mod  # noqa: PLC0415

        if _mkt_cache["data"] is not None and time_mod.time() - _mkt_cache["at"] < 600:
            return _mkt_cache["data"]  # 10분 캐시 — 첫 화면 진입마다 API 폭주 방지
        conn = _conn()
        try:
            data = market_summary(settings, conn)
        finally:
            conn.close()
        _mkt_cache.update(at=time_mod.time(), data=data)
        return data

    @app.get("/api/socra/sessions")
    def sessions_list():
        conn = _conn()
        try:
            return socra_sessions_list(conn)
        finally:
            conn.close()

    @app.get("/api/socra/sessions/{session_id}")
    def session_detail(session_id: str):
        conn = _conn()
        try:
            data = socra_session_detail(conn, session_id)
        finally:
            conn.close()
        if data is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return data

    @app.post("/api/socra/sessions")
    def session_create(payload: dict = Body(...)):
        if quick_llm is None:
            return JSONResponse({"error": "LLM 미설정"}, status_code=503)
        conn = _conn()
        try:
            return SocraEngine(conn, settings, quick_llm, deep_llm).start_session(
                str(payload.get("query", ""))
            )
        finally:
            conn.close()

    @app.post("/api/panel")
    def panel_run(payload: dict = Body(...)):
        """대가 패널 — 카드 확정 후 참고 관점 (일별 캐시)."""
        if quick_llm is None:
            return JSONResponse({"error": "LLM 미설정"}, status_code=503)
        from aim.panel import run_panel  # noqa: PLC0415

        conn = _conn()
        try:
            return run_panel(conn, settings, str(payload.get("symbol", "")), quick_llm)
        finally:
            conn.close()

    @app.post("/api/socra/requestion")
    def requestion_create(payload: dict = Body(...)):
        """근거 변화 알림 → 재질문 세션 (§4.5)."""
        if quick_llm is None:
            return JSONResponse({"error": "LLM 미설정"}, status_code=503)
        conn = _conn()
        try:
            return SocraEngine(conn, settings, quick_llm, deep_llm).start_requestion(
                str(payload.get("card_id", ""))
            )
        finally:
            conn.close()

    @app.post("/api/socra/sessions/{session_id}/messages")
    def session_message(session_id: str, payload: dict = Body(...)):
        if quick_llm is None:
            return JSONResponse({"error": "LLM 미설정"}, status_code=503)
        conn = _conn()
        try:
            return SocraEngine(conn, settings, quick_llm, deep_llm).handle_message(
                session_id, str(payload.get("text", ""))
            )
        finally:
            conn.close()

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
