-- 장중 폴링 관측치 — 시간대별 누적거래량 축적 → volume_baselines 재계산의 원천
-- (KIS는 과거 분봉 조회가 제한적이므로, 우리가 직접 폴링하며 프로파일을 학습한다)
CREATE TABLE intraday_observations (
    symbol      TEXT NOT NULL,
    obs_date    TEXT NOT NULL,    -- YYYY-MM-DD
    time_slot   TEXT NOT NULL,    -- HH:MM (5분 슬롯)
    cum_volume  REAL NOT NULL,    -- 해당 슬롯에서 마지막으로 관측된 누적거래량
    PRIMARY KEY (symbol, obs_date, time_slot)
);
