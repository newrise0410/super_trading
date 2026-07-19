-- S2: 사용자 지식 모델 + 전체 종목 검색

-- 개념 숙련도 — 범례 노출/질문/이해입증 신호로 갱신 (레벨 3 이상이면 범례 생략)
CREATE TABLE concept_mastery (
    user_id    TEXT NOT NULL DEFAULT 'local',
    slug       TEXT NOT NULL,
    level      INTEGER NOT NULL DEFAULT 0,   -- 0 미접촉 | 1 범례노출 | 2 질문함(미숙련) | 3 이해입증
    exposures  INTEGER NOT NULL DEFAULT 0,   -- 범례 노출 횟수
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, slug)
);

-- 상장 종목 마스터 (KIS mst 파일 동기화 — aim symbols-sync)
CREATE TABLE symbols (
    symbol    TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    market    TEXT NOT NULL,                 -- KOSPI | KOSDAQ
    name_norm TEXT NOT NULL                  -- 검색용 (소문자·공백 제거)
);
CREATE INDEX idx_symbols_norm ON symbols (name_norm);
