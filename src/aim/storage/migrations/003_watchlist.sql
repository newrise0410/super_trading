-- 관심종목 실시간 추적·시그널 (watch/ 모듈)

CREATE TABLE watchlist (
    symbol      TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    market      TEXT NOT NULL DEFAULT 'KR',
    active      INTEGER NOT NULL DEFAULT 1,
    added_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 발생한 시그널 이력 — 쿨다운 판정 + 사후 적중률 캘리브레이션 원천
CREATE TABLE signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id    TEXT NOT NULL UNIQUE,       -- uuid
    symbol       TEXT NOT NULL,
    kind         TEXT NOT NULL,              -- VOLUME_SURGE | VALUE_SPIKE | PRICE_MOVE | DISCLOSURE | COMBO
    severity     TEXT NOT NULL DEFAULT 'info',  -- info | notable | critical
    message      TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    fired_at     TEXT NOT NULL,              -- "YYYY-MM-DD HH:MM:SS" (KST)
    delivered    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_signals_symbol_kind ON signals (symbol, kind, fired_at DESC);

-- 시간대별 누적거래량 프로파일 (동시각 비교용 — 시간대 정규화의 핵심)
CREATE TABLE volume_baselines (
    symbol          TEXT NOT NULL,
    time_slot       TEXT NOT NULL,           -- 'HH:MM' (5분 슬롯)
    avg_cum_volume  REAL NOT NULL,           -- 과거 N일 동시각 누적거래량 평균
    std_cum_volume  REAL NOT NULL,
    days            INTEGER NOT NULL,        -- 표본 일수
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, time_slot)
);
