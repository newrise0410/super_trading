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
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    dry_run: bool
    db_path: Path
    telegram_bot_token: str
    telegram_chat_id: str
    kis_app_key: str
    kis_app_secret: str
    kis_env: str  # prod | vps(모의)
    dart_api_key: str
    llm_provider: str
    llm_api_key: str
    llm_deep_model: str
    llm_quick_model: str


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
        kis_app_key=env("AIM_KIS_APP_KEY", ""),
        kis_app_secret=env("AIM_KIS_APP_SECRET", ""),
        kis_env=env("AIM_KIS_ENV", "prod"),
        dart_api_key=env("AIM_DART_API_KEY", ""),
        llm_provider=env("AIM_LLM_PROVIDER", ""),
        llm_api_key=env("AIM_LLM_API_KEY", ""),
        llm_deep_model=env("AIM_LLM_DEEP_MODEL", ""),
        llm_quick_model=env("AIM_LLM_QUICK_MODEL", ""),
    )
