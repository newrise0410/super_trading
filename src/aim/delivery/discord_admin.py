"""디스코드 서버 프로비저닝 — 봇 토큰으로 채널·웹훅 자동 생성 (aim discord-setup).

멱등 설계: 이미 있는 카테고리/채널/웹훅은 재사용 — 몇 번을 실행해도 안전.
필요 봇 권한: Manage Channels + Manage Webhooks (초대 URL permissions=536870928).

채널 스펙(_CHANNEL_SPECS)에 추가하면 다음 실행 때 새 채널이 생긴다.
포럼 채널은 서버가 지원하지 않으면(커뮤니티 미활성 등) 텍스트 채널로 자동 폴백.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

API = "https://discord.com/api/v10"

# Discord 채널 타입
TYPE_TEXT = 0
TYPE_CATEGORY = 4
TYPE_FORUM = 15

CATEGORY_NAME = "AIM 투자매니저"
WEBHOOK_NAME = "AIM"

# (채널명, 채널타입, .env 키) — 여기에 추가하면 discord-setup이 새로 만든다
_CHANNEL_SPECS: list[tuple[str, int, str]] = [
    ("한국장-브리핑", TYPE_FORUM, "AIM_DISCORD_WEBHOOK_KR"),
    ("미국장-브리핑", TYPE_FORUM, "AIM_DISCORD_WEBHOOK_US"),
    ("관심종목-시그널", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_SIGNALS"),
    ("포트폴리오", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_PORTFOLIO"),  # AI 진단 리포트
    ("상담", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_CONSULT"),          # LLM 대화 (aim chat 봇)
]

ReqFn = Callable[[str, str, dict[str, Any] | None], tuple[int, Any]]
# (method, path, json_body) -> (status, data)


@dataclass
class ProvisionResult:
    env_updates: dict[str, str]     # .env 키 → 웹훅 URL
    created: list[str]              # 새로 만든 리소스 설명
    reused: list[str]               # 기존 재사용 리소스 설명
    warnings: list[str]


class DiscordAdmin:
    def __init__(self, bot_token: str, *, req_fn: ReqFn | None = None) -> None:
        if not bot_token:
            raise ValueError("AIM_DISCORD_BOT_TOKEN 설정이 필요합니다 (.env)")
        self._token = bot_token
        self._req = req_fn or self._default_req

    def _default_req(self, method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        import requests  # noqa: PLC0415

        resp = requests.request(
            method, f"{API}{path}",
            headers={"Authorization": f"Bot {self._token}"},
            json=body, timeout=15,
        )
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}

    # ── API 래퍼 ─────────────────────────────────────────────────

    def list_guilds(self) -> list[dict[str, Any]]:
        status, data = self._req("GET", "/users/@me/guilds", None)
        if status != 200:
            raise RuntimeError(f"길드 조회 실패 (HTTP {status}) — 봇 토큰을 확인하세요: {data}")
        return data

    def get_channels(self, guild_id: str) -> list[dict[str, Any]]:
        status, data = self._req("GET", f"/guilds/{guild_id}/channels", None)
        if status != 200:
            raise RuntimeError(f"채널 조회 실패 (HTTP {status}): {data}")
        return data

    def create_channel(
        self, guild_id: str, name: str, ch_type: int, parent_id: str | None = None
    ) -> tuple[int, Any]:
        body: dict[str, Any] = {"name": name, "type": ch_type}
        if parent_id:
            body["parent_id"] = parent_id
        return self._req("POST", f"/guilds/{guild_id}/channels", body)

    def get_webhooks(self, channel_id: str) -> list[dict[str, Any]]:
        status, data = self._req("GET", f"/channels/{channel_id}/webhooks", None)
        return data if status == 200 else []

    def create_webhook(self, channel_id: str) -> tuple[int, Any]:
        return self._req("POST", f"/channels/{channel_id}/webhooks", {"name": WEBHOOK_NAME})


# ── 프로비저닝 ───────────────────────────────────────────────────


def provision(admin: DiscordAdmin, guild_id: str) -> ProvisionResult:
    result = ProvisionResult({}, [], [], [])
    channels = admin.get_channels(guild_id)
    by_name = {c["name"]: c for c in channels}

    # 1) 카테고리 find-or-create
    category = next(
        (c for c in channels if c["type"] == TYPE_CATEGORY and c["name"] == CATEGORY_NAME), None
    )
    if category:
        result.reused.append(f"카테고리 '{CATEGORY_NAME}'")
    else:
        status, category = admin.create_channel(guild_id, CATEGORY_NAME, TYPE_CATEGORY)
        if status >= 400:
            raise RuntimeError(f"카테고리 생성 실패 (HTTP {status}): {category}")
        result.created.append(f"카테고리 '{CATEGORY_NAME}'")

    # 2) 채널 find-or-create (포럼 미지원 시 텍스트 폴백)
    for name, ch_type, env_key in _CHANNEL_SPECS:
        channel = by_name.get(name)
        if channel:
            result.reused.append(f"채널 #{name}")
        else:
            status, channel = admin.create_channel(guild_id, name, ch_type, category["id"])
            if status >= 400 and ch_type == TYPE_FORUM:
                result.warnings.append(
                    f"#{name}: 포럼 생성 불가(HTTP {status}) → 텍스트 채널로 대체. "
                    "서버 설정에서 '커뮤니티'를 활성화하면 포럼 사용 가능"
                )
                status, channel = admin.create_channel(guild_id, name, TYPE_TEXT, category["id"])
            if status >= 400:
                result.warnings.append(f"#{name}: 채널 생성 실패 (HTTP {status}): {channel}")
                continue
            kind = "포럼" if channel.get("type") == TYPE_FORUM else "텍스트"
            result.created.append(f"채널 #{name} ({kind})")

        # 3) 웹훅 find-or-create
        existing = [w for w in admin.get_webhooks(channel["id"]) if w.get("name") == WEBHOOK_NAME]
        if existing and existing[0].get("token"):
            webhook = existing[0]
            result.reused.append(f"웹훅 @{name}")
        else:
            status, webhook = admin.create_webhook(channel["id"])
            if status >= 400:
                result.warnings.append(f"#{name}: 웹훅 생성 실패 (HTTP {status}): {webhook}")
                continue
            result.created.append(f"웹훅 @{name}")

        result.env_updates[env_key] = (
            f"https://discord.com/api/webhooks/{webhook['id']}/{webhook['token']}"
        )

    return result


def update_env_file(env_path: Path, updates: dict[str, str]) -> list[str]:
    """.env에서 해당 키만 교체/추가 — 나머지 내용은 그대로 보존. 변경된 키 목록 반환."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    remaining = dict(updates)
    changed: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if "=" not in stripped or stripped.startswith("#"):
            continue
        key = stripped.partition("=")[0].strip()
        if key in remaining:
            new_line = f"{key}={remaining.pop(key)}"
            if line != new_line:
                lines[i] = new_line
                changed.append(key)

    for key, value in remaining.items():
        lines.append(f"{key}={value}")
        changed.append(key)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed
