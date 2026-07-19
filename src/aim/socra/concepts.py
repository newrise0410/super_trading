"""개념 사전 시드 (~15개) + 범례(1층) 용어 감지."""

from __future__ import annotations

import json
import sqlite3

# (slug, 표시명, 별칭들, 범례용 한 줄 정의 — 초보의 언어로)
SEED_CONCEPTS: list[tuple[str, str, list[str], str]] = [
    ("per", "PER", ["P/E", "주가수익비율"], "주가가 1년 이익의 몇 배인지 — 낮을수록 이익 대비 싼 편"),
    ("pbr", "PBR", ["주가순자산비율"], "주가가 회사 순자산의 몇 배인지 — 1배 미만이면 장부가보다 싸다는 뜻"),
    ("market_cap", "시가총액", ["시총"], "회사 전체의 가격표 (주가 × 주식 수)"),
    ("volume", "거래량", ["거래대금"], "오늘 이 주식이 얼마나 활발히 사고팔렸는지"),
    ("flow", "수급", ["외국인 순매수", "기관 순매수", "순매수", "순매도"], "누가 사고 누가 파는가 — 외국인·기관·개인의 매매 방향"),
    ("ma", "이동평균선", ["MA", "MA20", "MA60", "이평선", "정배열"], "최근 N일 평균 가격을 이은 선 — 추세를 보는 기본 도구"),
    ("rsi", "RSI", [], "과열/침체 온도계 (70 넘으면 과열, 30 아래면 과매도 신호로 봄)"),
    ("stop_loss", "손절", ["손절선", "손절가"], "여기까지 떨어지면 판다고 미리 정한 가격 — 큰 손실을 막는 안전벨트"),
    ("take_profit", "익절", ["목표가"], "여기까지 오르면 판다고 미리 정한 가격 — 욕심을 관리하는 장치"),
    ("split_buy", "분할매수", ["분할 매수"], "한 번에 다 사지 않고 나눠서 사는 것 — 타이밍 위험을 줄임"),
    ("dividend", "배당", ["배당금", "배당수익률"], "회사가 번 돈의 일부를 주주에게 나눠주는 것"),
    ("52w", "52주 신고가/신저가", ["52주"], "최근 1년 중 가장 높았던/낮았던 가격 — 현재 위치를 가늠하는 잣대"),
    ("disclosure", "공시", ["전자공시", "DART"], "회사가 의무적으로 알리는 공식 소식 (계약·증자·실적 등)"),
    ("earnings", "실적", ["영업이익", "매출"], "회사가 실제로 얼마나 벌었는지 — 주가의 장기 연료"),
    ("valuation", "밸류에이션", ["기업가치", "적정가치"], "이 회사가 얼마짜리인지 따져보는 일 — 가격과 가치는 다르다"),
    ("order_type", "시장가/지정가", ["시장가", "지정가"], "시장가 = 지금 당장 아무 가격에나 / 지정가 = 내가 정한 가격에만 사고팔기"),
    ("orderbook", "호가", ["호가창", "매수호가", "매도호가"], "사려는 사람과 팔려는 사람이 부른 가격이 줄 서 있는 판"),
    ("rights_issue", "유상증자", [], "회사가 새 주식을 찍어 돈을 받고 파는 것 — 내 지분이 희석될 수 있음"),
    ("bonus_issue", "무상증자", [], "회사가 새 주식을 공짜로 나눠주는 것 — 주식 수가 늘고 주가는 그만큼 조정"),
    ("stock_split", "액면분할", [], "주식 1장을 여러 장으로 쪼개는 것 — 가치는 그대로, 가격만 낮아져 사기 쉬워짐"),
    ("short_selling", "공매도", [], "주식을 빌려서 먼저 팔고 나중에 사서 갚는 것 — 떨어져야 돈 버는 방식"),
    ("margin", "신용거래", ["신용잔고", "미수"], "증권사 돈을 빌려서 주식을 사는 것 — 수익도 손실도 커지는 양날의 검"),
    ("market_kind", "코스피/코스닥", ["코스피", "코스닥"], "코스피 = 대형·전통 기업 시장 / 코스닥 = 중소·성장 기업 시장"),
    ("etf", "ETF", ["상장지수펀드"], "여러 주식을 한 바구니에 담아 주식처럼 사고파는 상품"),
    ("ex_dividend", "배당락", [], "배당 받을 권리가 사라지는 날 — 그날 주가가 배당만큼 내려가는 게 보통"),
    ("surprise", "어닝서프라이즈", ["어닝쇼크"], "실적이 예상보다 훨씬 좋음(서프라이즈)/나쁨(쇼크) — 주가가 크게 반응"),
    ("consensus", "컨센서스", ["목표주가", "애널리스트 전망"], "증권사 애널리스트들의 평균 전망치 — 시장의 기대선"),
    ("averaging_down", "물타기", ["추가매수"], "떨어질 때 더 사서 평단가를 낮추는 것 — 근거 없이 하면 손실만 키움"),
    ("diversification", "분산투자", ["몰빵"], "한 종목에 다 걸지 않고 나누는 것 — 하나가 틀려도 살아남기 위해"),
]


def seed_concepts(conn: sqlite3.Connection) -> int:
    """개념 사전 시드 (멱등). 삽입/갱신 수 반환."""
    for slug, term, aliases, short_def in SEED_CONCEPTS:
        conn.execute(
            "INSERT INTO concepts (slug, term, aliases, short_def) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(slug) DO UPDATE SET term=excluded.term, aliases=excluded.aliases,"
            " short_def=excluded.short_def",
            (slug, term, json.dumps(aliases, ensure_ascii=False), short_def),
        )
    conn.commit()
    return len(SEED_CONCEPTS)


def detect_terms(conn: sqlite3.Connection, text: str) -> list[dict]:
    """텍스트에 등장한 개념 → 범례 목록 [{slug, term, short_def}] (등장 순, 중복 제거)."""
    found: list[dict] = []
    seen: set[str] = set()
    rows = conn.execute("SELECT slug, term, aliases, short_def FROM concepts").fetchall()
    matches: list[tuple[int, dict]] = []
    for row in rows:
        keywords = [row["term"], *json.loads(row["aliases"])]
        positions = [text.find(k) for k in keywords if k and k in text]
        if positions:
            matches.append((min(positions), {
                "slug": row["slug"], "term": row["term"], "short_def": row["short_def"],
            }))
    for _pos, item in sorted(matches, key=lambda x: x[0]):
        if item["term"] not in seen:
            seen.add(item["term"])
            found.append(item)
    return found[:5]  # 범례는 최대 5개 — 압도하지 않기
