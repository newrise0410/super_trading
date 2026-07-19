-- S3: 살아있는 결정 카드 (§4.5) — 세션 종류(여정/재질문) + 카드 알림 이력

ALTER TABLE socra_sessions ADD COLUMN kind TEXT NOT NULL DEFAULT 'journey';  -- journey | recheck
ALTER TABLE socra_sessions ADD COLUMN ref_card_id TEXT;                      -- recheck의 대상 카드

-- 카드 감시 알림 이력 — 중복 억제(같은 kind 3일) + 재질문 유도 기록
CREATE TABLE card_alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id    TEXT NOT NULL REFERENCES decision_cards(card_id),
    kind       TEXT NOT NULL,     -- price_target | price_stop | flip:<evidence_key> | recheck:<n>
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_card_alerts ON card_alerts (card_id, kind, created_at DESC);
