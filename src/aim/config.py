"""환경설정 — .env 파일(있으면) + 환경변수 로드. 외부 의존성 없이 동작한다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """python-dotenv 없이 동작하는 미니 .env 로더 (이미 설정된 환경변수는 우선)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.split("#")[0].strip()
        # 빈 값 줄은 무시 — 같은 키가 뒤에 다시 나오면 그 값을 쓸 수 있게
        if key and value and key not in os.environ:
            os.environ[key] = value


def _collect_discord_webhooks() -> dict[str, str]:
    """AIM_DISCORD_WEBHOOK_* 환경변수 → {route: url}. _URL 접미사는 "default"."""
    prefix = "AIM_DISCORD_WEBHOOK_"
    webhooks: dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix) or not value.strip():
            continue
        suffix = key[len(prefix):].lower()
        route = "default" if suffix == "url" else suffix
        webhooks[route] = value.strip()
    return webhooks


@dataclass(frozen=True)
class Settings:
    dry_run: bool
    db_path: Path
    telegram_bot_token: str
    telegram_chat_id: str
    # route(소문자) → 웹훅 URL. AIM_DISCORD_WEBHOOK_URL → "default",
    # AIM_DISCORD_WEBHOOK_KR → "kr", _US → "us", _SIGNALS → "signals",
    # _SURGE → "surge", _DISCLOSURE → "disclosure" ... (임의 접미사 허용)
    discord_webhooks: dict[str, str]
    discord_bot_token: str   # discord-setup(서버 프로비저닝)용 — 발송에는 불필요
    discord_guild_id: str    # 봇이 여러 서버에 있을 때만 지정
    discord_owner_id: str    # 상담 봇 응답 대상 오버라이드 (기본: 서버 오너 자동 감지)
    kis_app_key: str
    kis_app_secret: str
    kis_env: str  # prod | vps(모의)
    kis_account_no: str  # "12345678-01" — 잔고 동기화(aim portfolio sync)용, 조회 전용
    dart_api_key: str
    # LLM 2-티어: 딥씽킹(판정자) = Codex CLI (ChatGPT 구독 OAuth, 토큰 갱신은 CLI가 담당)
    #             퀵씽킹(애널리스트) = MiniMax API
    minimax_api_key: str
    minimax_model: str
    minimax_base_url: str
    codex_model: str  # 비우면 Codex CLI 기본 모델


def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ.get

    db_path = Path(env("AIM_DB_PATH", "data/aim.db"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    return Settings(
        dry_run=env("AIM_DRY_RUN", "true").lower() in ("1", "true", "yes"),
        db_path=db_path,
        telegram_bot_token=env("AIM_TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=env("AIM_TELEGRAM_CHAT_ID", ""),
        discord_webhooks=_collect_discord_webhooks(),
        discord_bot_token=env("AIM_DISCORD_BOT_TOKEN", ""),
        discord_guild_id=env("AIM_DISCORD_GUILD_ID", ""),
        discord_owner_id=env("AIM_DISCORD_OWNER_ID", ""),
        kis_app_key=env("AIM_KIS_APP_KEY", ""),
        kis_app_secret=env("AIM_KIS_APP_SECRET", ""),
        kis_env=env("AIM_KIS_ENV", "prod"),
        kis_account_no=env("AIM_KIS_ACCOUNT_NO", ""),
        dart_api_key=env("AIM_DART_API_KEY", ""),
        minimax_api_key=env("AIM_MINIMAX_API_KEY", ""),
        minimax_model=env("AIM_MINIMAX_MODEL", "MiniMax-M3"),
        minimax_base_url=env("AIM_MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
        codex_model=env("AIM_CODEX_MODEL", ""),
    )
