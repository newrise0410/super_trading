-- 판단 로그 스키마는 처음부터 서비스 기준으로 (PLAN.md §10.6-4)
-- Q&A(/why, /prob)와 확률 캘리브레이션의 원천 데이터

-- 마스터 리포트 (§10.6-2: 마스터/개인 분리)
CREATE TABLE reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   TEXT NOT NULL UNIQUE,          -- uuid
    kind        TEXT NOT NULL,                 -- kr_open | kr_close | us_open | us_close | weekly
    market      TEXT NOT NULL,                 -- KR | US | ALL
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    master_md   TEXT NOT NULL,                 -- 마스터 리포트 본문 (markdown)
    data_json   TEXT NOT NULL DEFAULT '{}',    -- 구조화 데이터 스냅샷 (지수·수급·특징주)
    status      TEXT NOT NULL DEFAULT 'draft'  -- draft | published | failed
);
CREATE INDEX idx_reports_kind_created ON reports (kind, created_at DESC);

-- 종목 판단 로그 — 모든 권고의 근거·확률·데이터 스냅샷
CREATE TABLE decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         TEXT NOT NULL UNIQUE,   -- uuid
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    market              TEXT NOT NULL,          -- KR | US
    symbol              TEXT NOT NULL,          -- 005930 | AAPL
    name                TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL,          -- BUY | SELL | HOLD | WATCH
    confidence          REAL,                   -- 0.0 ~ 1.0 (LLM 자체 확신도)
    horizon             TEXT,                   -- 예: 5d, 1m
    entry_price         REAL,
    target_price        REAL,
    stop_price          REAL,
    strategy            TEXT NOT NULL,          -- 어느 전략/파이프라인의 판단인가 (rule_v1, ai_debate, ...)
    rationale_json      TEXT NOT NULL DEFAULT '[]',  -- [{type, text, weight}] 구조화 근거
    risks_json          TEXT NOT NULL DEFAULT '[]',  -- Bear 논점/리스크
    debate_log_json     TEXT NOT NULL DEFAULT '[]',  -- P2: bull/bear 토론 턴 전문
    data_snapshot_json  TEXT NOT NULL DEFAULT '{}',  -- 판단 시점의 시세·수급 스냅샷 (재현용)
    report_id           TEXT REFERENCES reports(report_id),
    -- 반성 루프 (사후 기록)
    outcome_return_5d   REAL,
    outcome_evaluated_at TEXT
);
CREATE INDEX idx_decisions_symbol ON decisions (symbol, created_at DESC);
CREATE INDEX idx_decisions_strategy ON decisions (strategy, created_at DESC);

-- 전략 시뮬레이션 (P3 예약 — 스키마만 선정의)
CREATE TABLE virtual_portfolios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy      TEXT NOT NULL UNIQUE,       -- ai_debate | momentum | canslim | value | quant | benchmark
    market        TEXT NOT NULL,
    initial_cash  REAL NOT NULL,
    cash          REAL NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE virtual_positions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id  INTEGER NOT NULL REFERENCES virtual_portfolios(id),
    symbol        TEXT NOT NULL,
    quantity      REAL NOT NULL,
    avg_price     REAL NOT NULL,
    opened_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (portfolio_id, symbol)
);

CREATE TABLE virtual_trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id  INTEGER NOT NULL REFERENCES virtual_portfolios(id),
    decision_id   TEXT REFERENCES decisions(decision_id),  -- 모든 거래는 판단에 연결 (감사 추적)
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL,              -- BUY | SELL
    quantity      REAL NOT NULL,
    price         REAL NOT NULL,
    executed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
