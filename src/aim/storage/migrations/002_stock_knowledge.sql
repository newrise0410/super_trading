-- 종목 지식 저장소 (PLAN.md §13) — 분석 결과를 팩트 단위로 청킹·캐시
-- 원칙: 비싼 추론(LLM 분석)만 저장, 싼 데이터(시세·수급)는 항상 라이브 조회

CREATE TABLE stock_facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id             TEXT NOT NULL UNIQUE,        -- uuid
    market              TEXT NOT NULL,               -- KR | US
    symbol              TEXT NOT NULL,
    fact_type           TEXT NOT NULL,               -- profile | business | financials | catalyst | thesis | risk | technicals | flow | outcome
    topic               TEXT NOT NULL DEFAULT '',    -- 대체(supersede) 키: 같은 (symbol, fact_type, topic)은 최신 팩트가 대체
    content             TEXT NOT NULL,               -- 팩트 본문 (자족적 한 단락 — 청크 단위)
    as_of               TEXT NOT NULL,               -- 이 사실의 기준 시점 (YYYY-MM-DD)
    valid_until         TEXT,                        -- NULL = 무기한. 지나면 stale (조회 시 기본 제외)
    confidence          REAL,
    source_report_id    TEXT REFERENCES reports(report_id),
    source_decision_id  TEXT REFERENCES decisions(decision_id),
    superseded_by       TEXT,                        -- 최신 fact_id로 대체됨 (삭제 대신 이력 보존)
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    embedding           BLOB                         -- P4: 임베딩 리랭크용 (v1은 FTS5만)
);
CREATE INDEX idx_facts_symbol ON stock_facts (symbol, fact_type, as_of DESC);
CREATE INDEX idx_facts_active ON stock_facts (symbol, superseded_by) WHERE superseded_by IS NULL;

-- FTS5 전문검색 (external content — 본문 중복 저장 방지)
CREATE VIRTUAL TABLE stock_facts_fts USING fts5(
    content,
    content='stock_facts',
    content_rowid='id'
);

CREATE TRIGGER stock_facts_ai AFTER INSERT ON stock_facts BEGIN
    INSERT INTO stock_facts_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER stock_facts_ad AFTER DELETE ON stock_facts BEGIN
    INSERT INTO stock_facts_fts(stock_facts_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER stock_facts_au AFTER UPDATE ON stock_facts BEGIN
    INSERT INTO stock_facts_fts(stock_facts_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO stock_facts_fts(rowid, content) VALUES (new.id, new.content);
END;
