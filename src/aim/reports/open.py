"""장전 브리핑 (PLAN §4 — KR 08:30 / US 22:30)."""

from __future__ import annotations

import logging

from aim.reports.master import DISCLAIMER, _fmt_pct
from aim.watch.models import Disclosure
from aim.watch.signals import CATEGORY_LABEL, classify_disclosure

logger = logging.getLogger(__name__)

US_FUTURES = (("S&P500 선물", "ES=F"), ("나스닥 선물", "NQ=F"), ("다우 선물", "YM=F"))


def fetch_us_futures() -> list[tuple[str, float, float]]:
    """[(이름, 가격, 등락%)] — 실패 항목 제외."""
    import yfinance as yf  # noqa: PLC0415

    result = []
    for name, ticker in US_FUTURES:
        try:
            info = yf.Ticker(ticker).fast_info
            price = float(info["last_price"])
            prev = float(info["previous_close"])
            result.append((name, price, round((price / prev - 1) * 100 if prev else 0.0, 2)))
        except Exception:  # noqa: BLE001
            logger.warning("futures fetch failed: %s", name)
    return result


def _index_lines(indices: list[tuple[str, float, float]]) -> list[str]:
    return [f"- **{n}** {p:,.2f} {_fmt_pct(c)}" for n, p, c in indices] or ["- (조회 실패)"]


def build_kr_open_briefing(
    date: str,
    us_indices: list[tuple[str, float, float]],
    usdkrw: float | None,
    disclosures: list[Disclosure],
    recent_signals: list[dict],
    watch_names: list[str],
    personal_md: str,
) -> str:
    parts = [f"# 🇰🇷 장전 브리핑 · {date}\n", "## 🌙 간밤 미국 증시"]
    parts += _index_lines(us_indices)
    if usdkrw:
        parts.append(f"- **USD/KRW** {usdkrw:,.1f}")

    if disclosures:
        parts.append("\n## 📢 관심·보유 종목 새 공시")
        for d in disclosures[:8]:
            category = CATEGORY_LABEL.get(classify_disclosure(d.title), "기타")
            parts.append(f"- **{d.corp_name}** [{category}] {d.title} ({d.filed_at})")

    if recent_signals:
        parts.append("\n## 🔔 최근 24시간 시그널")
        for s in recent_signals[:6]:
            parts.append(f"- {s['fired_at'][5:16]} **{s['symbol']}** [{s['kind']}] {s['message']}")

    if watch_names:
        parts.append(f"\n## 👀 오늘의 관심 종목\n- {' · '.join(watch_names)}")

    if personal_md:
        parts.append(f"\n{personal_md}")
    parts.append("\n---\n" + DISCLAIMER)
    return "\n".join(parts)


def build_us_open_briefing(
    date: str,
    futures: list[tuple[str, float, float]],
    kr_summary: list[tuple[str, float, float]],
    usdkrw: float | None,
) -> str:
    parts = [f"# 🇺🇸 장전 브리핑 · {date}\n", "## 📈 지수 선물"]
    parts += _index_lines(futures)
    if kr_summary:
        parts.append("\n## 🇰🇷 오늘 한국장 마감")
        parts += _index_lines(kr_summary)
    if usdkrw:
        parts.append(f"- **USD/KRW** {usdkrw:,.1f}")
    parts.append("\n---\n" + DISCLAIMER)
    return "\n".join(parts)
