-- OpenDART 공시 중복 제거 — 이미 처리한 접수번호(rcept_no) 기록
CREATE TABLE dart_seen (
    rcept_no  TEXT PRIMARY KEY,
    seen_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
