-- 소크라 v2 (PLAN §5) — 대화 세션·결정 카드·개념 사전

CREATE TABLE socra_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL UNIQUE,          -- uuid
    user_id       TEXT NOT NULL DEFAULT 'local', -- S4에서 실사용자 (처음부터 스코핑)
    symbol        TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    stage         TEXT NOT NULL DEFAULT 'business',  -- business|valuation|risk|exit|card|done
    evidence_md   TEXT NOT NULL DEFAULT '',      -- 세션 시작 시 수집한 증거 (질문·레슨 근거)
    card_draft_json TEXT,                        -- deep 모델이 정리한 카드 초안
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_socra_sessions_user ON socra_sessions (user_id, updated_at DESC);

CREATE TABLE socra_turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES socra_sessions(session_id),
    role        TEXT NOT NULL,                   -- bot | user
    content     TEXT NOT NULL,
    stage       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_socra_turns_session ON socra_turns (session_id, id);

-- 결정 카드 — 사용자가 스스로 세운 논지·기준 (v1 decisions와 별도; §4.5 근거 동결 포함)
CREATE TABLE decision_cards (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id            TEXT NOT NULL UNIQUE,
    session_id         TEXT REFERENCES socra_sessions(session_id),
    user_id            TEXT NOT NULL DEFAULT 'local',
    symbol             TEXT NOT NULL,
    name               TEXT NOT NULL DEFAULT '',
    version            INTEGER NOT NULL DEFAULT 1,
    thesis             TEXT NOT NULL,             -- 사용자의 언어로 된 매수 논지
    target_price       REAL,
    target_reason      TEXT,
    stop_price         REAL,
    stop_reason        TEXT,
    recheck_conditions TEXT NOT NULL DEFAULT '[]', -- ["외인 순매도 전환", ...] — §4.5 감시 대상
    confidence_self    INTEGER,                    -- 사용자 자가평가 0~100
    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}', -- 근거 동결 (diff 기준점)
    status             TEXT NOT NULL DEFAULT 'active', -- active | superseded
    superseded_by      TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_cards_user_symbol ON decision_cards (user_id, symbol, created_at DESC);

-- 개념 사전 — 범례(1층)·온디맨드 설명(2층)의 원천
CREATE TABLE concepts (
    slug       TEXT PRIMARY KEY,      -- per, market_cap, ...
    term       TEXT NOT NULL,         -- 표시 이름 (PER)
    aliases    TEXT NOT NULL DEFAULT '[]',  -- 감지용 별칭 ["피이알", "주가수익비율"]
    short_def  TEXT NOT NULL          -- 범례용 한 줄 정의
);
