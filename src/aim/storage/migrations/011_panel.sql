-- 대가 페르소나 패널 (ai-hedge-fund 개념, MIT — 자체 구현) — 일별 캐시
CREATE TABLE panel_runs (
    symbol         TEXT NOT NULL,
    run_date       TEXT NOT NULL,               -- YYYY-MM-DD (하루 1회 캐시)
    name           TEXT NOT NULL DEFAULT '',
    verdicts_json  TEXT NOT NULL,               -- [{persona, stance, confidence, thesis, key_metric}]
    consensus_json TEXT NOT NULL,               -- {counts, majority, agreement_pct}
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, run_date)
);
