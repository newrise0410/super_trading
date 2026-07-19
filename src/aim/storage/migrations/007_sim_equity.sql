-- 전략 시뮬레이션 일별 평가액 — 수익률·MDD 계산의 원천
CREATE TABLE sim_equity (
    portfolio_id  INTEGER NOT NULL REFERENCES virtual_portfolios(id),
    date          TEXT NOT NULL,
    value         REAL NOT NULL,
    PRIMARY KEY (portfolio_id, date)
);
