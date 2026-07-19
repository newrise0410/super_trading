"""전체 상장 종목 검색 (S2) — KIS 종목 마스터 파일 동기화.

스펙 기준: references/open-trading-api/stocks_info/kis_kospi_code_mst.py (자체 재구현)
- 행 구조: 단축코드(9) + 표준코드(12) + 한글명(나머지) + 고정 테일(KOSPI 228 / KOSDAQ 222)
- 인증 불필요 (공개 다운로드 서버)
"""

from __future__ import annotations

import io
import logging
import re
import sqlite3
import zipfile

logger = logging.getLogger(__name__)

MST_SOURCES = [
    ("KOSPI", "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
     "kospi_code.mst", 228),
    ("KOSDAQ", "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
     "kosdaq_code.mst", 222),
]


def _normalize(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


# 은어·줄임말 → 정식 종목명(정규화형). 초보의 실제 입력 습관 반영.
SLANG_ALIASES = {
    "삼전": "삼성전자", "하닉": "sk하이닉스", "엔솔": "lg에너지솔루션",
    "현차": "현대차", "셀트": "셀트리온", "삼바": "삼성바이오로직스",
    "카뱅": "카카오뱅크", "포홀": "포스코홀딩스", "두산에너": "두산에너빌리티",
    "한화에어로": "한화에어로스페이스", "네이버": "naver",
}


def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def suggest_symbols(conn: sqlite3.Connection, text: str, limit: int = 4) -> list[tuple[str, str]]:
    """검색 실패 시 유사 종목 후보 — 오타("삼송전자")·부분 기억 대응.

    문자 2그램 겹침 + 글자 커버리지로 스코어. 확신 없는 후보는 안 내는 게 낫다.
    """
    norm = _normalize(text)
    if len(norm) < 2:
        return []
    grams, chars = _bigrams(norm), set(norm)
    scored: list[tuple[int, float, str, str]] = []
    for r in conn.execute("SELECT symbol, name, name_norm FROM symbols WHERE length(name_norm) >= 2"):
        nn = r["name_norm"]
        b_overlap = len(grams & _bigrams(nn))
        c_cover = len(chars & set(nn)) / len(set(nn))
        if b_overlap >= 1 and c_cover >= 0.6:
            scored.append((b_overlap, c_cover, r["symbol"], r["name"]))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [(t[2], t[3]) for t in scored[:limit]]


def parse_mst(raw: bytes, tail_len: int) -> list[tuple[str, str]]:
    """mst 본문 → [(단축코드, 한글명)]. 6자리 표준 종목코드만."""
    rows: list[tuple[str, str]] = []
    for line in raw.decode("cp949", errors="ignore").splitlines():
        if len(line) <= tail_len + 21:
            continue
        head = line[: len(line) - tail_len]
        code = head[:9].strip()
        name = head[21:].strip()
        if re.fullmatch(r"\d{6}", code) and name:
            rows.append((code, name))
    return rows


def sync_symbols(conn: sqlite3.Connection, *, fetch=None) -> int:
    """마스터 파일 다운로드 → symbols 테이블 갱신. 총 종목 수 반환."""
    import requests  # noqa: PLC0415

    fetch = fetch or (lambda url: requests.get(url, timeout=30).content)
    total = 0
    for market, url, inner_name, tail_len in MST_SOURCES:
        try:
            payload = fetch(url)
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                raw = zf.read(inner_name)
            rows = parse_mst(raw, tail_len)
            for code, name in rows:
                conn.execute(
                    "INSERT INTO symbols (symbol, name, market, name_norm) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(symbol) DO UPDATE SET name = excluded.name,"
                    " market = excluded.market, name_norm = excluded.name_norm",
                    (code, name, market, _normalize(name)),
                )
            conn.commit()
            total += len(rows)
            logger.info("symbols synced: %s %d", market, len(rows))
        except Exception:  # noqa: BLE001 — 시장별 실패 격리
            logger.exception("symbol sync failed for %s", market)
    return total


def search_symbol(conn: sqlite3.Connection, text: str) -> tuple[str, str] | None:
    """자유 텍스트에서 종목 찾기 — 정확 일치 → 포함 일치(이름 짧은 순)."""
    norm = _normalize(text)
    if not norm:
        return None
    row = conn.execute(
        "SELECT symbol, name FROM symbols WHERE name_norm = ?", (norm,)
    ).fetchone()
    if row:
        return row["symbol"], row["name"]
    # 문장 속 포함 검색: "삼성전자 살까?" → name_norm이 문장에 포함된 종목 중 가장 긴 이름
    candidates = conn.execute(
        "SELECT symbol, name, name_norm FROM symbols WHERE length(name_norm) >= 2"
    ).fetchall()
    best = None
    for c in candidates:
        if c["name_norm"] in norm and (best is None or len(c["name_norm"]) > len(best["name_norm"])):
            best = c
    return (best["symbol"], best["name"]) if best else None
