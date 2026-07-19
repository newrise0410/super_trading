-- 내 실제 보유 종목 (virtual_* 시뮬레이션과 별개)
CREATE TABLE portfolio_positions (
    symbol      TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    market      TEXT NOT NULL DEFAULT 'KR',
    quantity    REAL NOT NULL,
    avg_price   REAL NOT NULL,          -- 평균 매수단가
    memo        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
