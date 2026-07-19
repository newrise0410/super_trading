"""KIS 계좌 잔고 동기화 — 실계좌 보유 종목을 portfolio_positions로 가져온다 (조회 전용).

스펙 기준: references/open-trading-api examples_llm/domestic_stock/inquire_balance
- TR: TTTC8434R(실전) / VTTC8434R(모의), GET /uapi/domestic-stock/v1/trading/inquire-balance
- 계좌번호: AIM_KIS_ACCOUNT_NO="12345678-01" (종합계좌 8자리 - 상품코드 2자리)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from aim.data.kis.auth import KISAuth

logger = logging.getLogger(__name__)

_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"

GetFn = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]


def _default_get(url: str, headers: dict[str, str], params: dict[str, str]) -> dict[str, Any]:
    import requests  # noqa: PLC0415

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_balance(
    auth: KISAuth, account_no: str, *, get_fn: GetFn | None = None
) -> list[dict[str, Any]]:
    """보유 종목 목록 반환: [{symbol, name, quantity, avg_price}]. 잔고 0 종목 제외."""
    if "-" not in account_no:
        raise ValueError('AIM_KIS_ACCOUNT_NO 형식: "12345678-01" (계좌 8자리-상품코드 2자리)')
    cano, prdt = account_no.split("-", 1)
    tr_id = "TTTC8434R" if auth.env == "prod" else "VTTC8434R"
    get = get_fn or _default_get

    data = get(
        f"{auth.base_url}{_PATH}",
        auth.headers(tr_id),
        {
            "CANO": cano, "ACNT_PRDT_CD": prdt,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        },
    )
    if data.get("rt_cd") != "0":
        raise RuntimeError(f"잔고 조회 실패: {data.get('msg1', data.get('rt_cd'))}")

    positions: list[dict[str, Any]] = []
    for row in data.get("output1") or []:
        quantity = float(row.get("hldg_qty") or 0)
        if quantity <= 0:
            continue
        positions.append({
            "symbol": (row.get("pdno") or "").strip(),
            "name": (row.get("prdt_name") or "").strip(),
            "quantity": quantity,
            "avg_price": float(row.get("pchs_avg_pric") or 0),
        })
    return positions
