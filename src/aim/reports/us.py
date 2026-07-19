"""미국장 마감 브리핑 (P4) — yfinance 지수 + 환율 + 내 미국 보유 성과."""

from __future__ import annotations

import logging

from aim.reports.master import DISCLAIMER, _fmt_pct

logger = logging.getLogger(__name__)

US_INDICES = (("S&P500", "^GSPC"), ("NASDAQ", "^IXIC"), ("다우존스", "^DJI"), ("필라델피아 반도체", "^SOX"))


def fetch_us_indices() -> list[tuple[str, float, float]]:
    """[(이름, 종가, 등락%)] — 실패 지수는 제외 (격리)."""
    import yfinance as yf  # noqa: PLC0415

    result = []
    for name, ticker in US_INDICES:
        try:
            info = yf.Ticker(ticker).fast_info
            price = float(info["last_price"])
            prev = float(info["previous_close"])
            change = (price / prev - 1) * 100 if prev else 0.0
            result.append((name, price, round(change, 2)))
        except Exception:  # noqa: BLE001
            logger.warning("US index fetch failed: %s", name)
    return result


def build_us_close_briefing(
    date: str,
    indices: list[tuple[str, float, float]],
    usdkrw: float | None,
    personal_md: str,
) -> str:
    parts = [f"# 🇺🇸 미국장 마감 브리핑 · {date}\n", "## 📊 지수 마감"]
    if indices:
        for name, price, change in indices:
            parts.append(f"- **{name}** {price:,.2f} {_fmt_pct(change)}")
    else:
        parts.append("- (지수 조회 실패)")
    if usdkrw:
        parts.append(f"- **USD/KRW** {usdkrw:,.1f}")
    if personal_md:
        parts.append(f"\n{personal_md}")
    parts.append("\n---\n" + DISCLAIMER)
    return "\n".join(parts)
