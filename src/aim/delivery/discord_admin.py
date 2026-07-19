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

# 권한 비트
PERM_VIEW = 1024          # VIEW_CHANNEL
PERM_SEND = 2048          # SEND_MESSAGES

WEBHOOK_NAME = "AIM"
OLD_CATEGORY_NAME = "AIM 투자매니저"  # 구버전 단일 카테고리 — 비면 정리

# (카테고리, 채널명, 채널타입, .env 키, 비공개 여부)
# 비공개: @everyone 숨김 + 봇만 접근 (서버 오너는 관리자라 항상 접근 가능)
_CHANNEL_SPECS: list[tuple[str, str, int, str, bool]] = [
    # 📁 리포트
    ("AIM 리포트", "한국장-브리핑", TYPE_FORUM, "AIM_DISCORD_WEBHOOK_KR", False),
    ("AIM 리포트", "미국장-브리핑", TYPE_FORUM, "AIM_DISCORD_WEBHOOK_US", False),
    # 📁 시그널 — surge/disclosure는 라우터 폴백 체인이 자동 우선 사용
    ("AIM 시그널", "관심종목-시그널", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_SIGNALS", False),
    ("AIM 시그널", "급등주", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_SURGE", False),
    ("AIM 시그널", "공시", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_DISCLOSURE", False),
    ("AIM 시그널", "긴급", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_URGENT", False),  # critical 횡단
    # 📁 프라이빗 (전부 🔒)
    ("AIM 프라이빗", "포트폴리오", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_PORTFOLIO", True),
    ("AIM 프라이빗", "상담", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_CONSULT", True),
    ("AIM 프라이빗", "ai-판단", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_DECISIONS", True),
    ("AIM 프라이빗", "전략-시뮬", TYPE_TEXT, "AIM_DISCORD_WEBHOOK_SIM", True),
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

    def bot_user_id(self) -> str:
        status, data = self._req("GET", "/users/@me", None)
        if status != 200:
            raise RuntimeError(f"봇 정보 조회 실패 (HTTP {status}): {data}")
        return str(data["id"])

    def set_private(self, channel_id: str, guild_id: str, bot_id: str) -> bool:
        """@everyone 숨김 + 봇 접근 허용. 성공 여부 반환."""
        status, data = self._req("PATCH", f"/channels/{channel_id}", {
            "permission_overwrites": [
                {"id": guild_id, "type": 0, "deny": str(PERM_VIEW), "allow": "0"},   # @everyone
                {"id": bot_id, "type": 1, "allow": str(PERM_VIEW + PERM_SEND), "deny": "0"},
            ]
        })
        if status >= 400:
            logger.warning("set_private failed for %s: %s", channel_id, data)
        return status < 400

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

    def move_channel(self, channel_id: str, parent_id: str) -> bool:
        status, data = self._req("PATCH", f"/channels/{channel_id}", {"parent_id": parent_id})
        if status >= 400:
            logger.warning("move_channel failed for %s: %s", channel_id, data)
        return status < 400

    def delete_channel(self, channel_id: str) -> bool:
        status, _ = self._req("DELETE", f"/channels/{channel_id}", None)
        return status < 400

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
    bot_id = admin.bot_user_id()

    # 1) 카테고리 find-or-create (스펙 등장 순서 유지)
    category_ids: dict[str, str] = {}
    for cat_name in dict.fromkeys(spec[0] for spec in _CHANNEL_SPECS):
        category = next(
            (c for c in channels if c["type"] == TYPE_CATEGORY and c["name"] == cat_name), None
        )
        if category:
            result.reused.append(f"카테고리 '{cat_name}'")
        else:
            status, category = admin.create_channel(guild_id, cat_name, TYPE_CATEGORY)
            if status >= 400:
                raise RuntimeError(f"카테고리 생성 실패 (HTTP {status}): {category}")
            result.created.append(f"카테고리 '{cat_name}'")
        category_ids[cat_name] = category["id"]

    # 2) 채널 find-or-create + 카테고리 재배치 + 비공개 권한 보장 (전부 멱등)
    for cat_name, name, ch_type, env_key, private in _CHANNEL_SPECS:
        parent_id = category_ids[cat_name]
        channel = by_name.get(name)
        if channel:
            result.reused.append(f"채널 #{name}")
            if channel.get("parent_id") != parent_id:
                if admin.move_channel(channel["id"], parent_id):
                    result.created.append(f"→ #{name} '{cat_name}'로 이동")
                else:
                    result.warnings.append(f"#{name}: 카테고리 이동 실패")
        else:
            status, channel = admin.create_channel(guild_id, name, ch_type, parent_id)
            if status >= 400 and ch_type == TYPE_FORUM:
                result.warnings.append(
                    f"#{name}: 포럼 생성 불가(HTTP {status}) → 텍스트 채널로 대체. "
                    "서버 설정에서 '커뮤니티'를 활성화하면 포럼 사용 가능"
                )
                status, channel = admin.create_channel(guild_id, name, TYPE_TEXT, parent_id)
            if status >= 400:
                result.warnings.append(f"#{name}: 채널 생성 실패 (HTTP {status}): {channel}")
                continue
            kind = "포럼" if channel.get("type") == TYPE_FORUM else "텍스트"
            result.created.append(f"채널 #{name} ({kind})")

        if private:
            if admin.set_private(channel["id"], guild_id, bot_id):
                result.reused.append(f"🔒 #{name} 비공개 권한 적용")
            else:
                result.warnings.append(f"#{name}: 비공개 권한 설정 실패")

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

    # 4) 구버전 카테고리 정리 — 비었으면 삭제
    old = next(
        (c for c in channels if c["type"] == TYPE_CATEGORY and c["name"] == OLD_CATEGORY_NAME), None
    )
    if old:
        refreshed = admin.get_channels(guild_id)
        if not any(c.get("parent_id") == old["id"] for c in refreshed):
            if admin.delete_channel(old["id"]):
                result.created.append(f"정리: 빈 카테고리 '{OLD_CATEGORY_NAME}' 삭제")

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
