"""discord-setup 프로비저닝 — 멱등성·포럼 폴백·.env 갱신 검증 (API는 fake 주입)."""

import pytest

from aim.delivery.discord_admin import (
    TYPE_CATEGORY,
    TYPE_FORUM,
    TYPE_TEXT,
    DiscordAdmin,
    provision,
    update_env_file,
)


class FakeDiscordAPI:
    """길드/채널/웹훅 상태를 시뮬레이션하는 인메모리 Discord API."""

    def __init__(self, *, forum_supported=True):
        self.forum_supported = forum_supported
        self.channels: list[dict] = []
        self.webhooks: dict[str, list[dict]] = {}  # channel_id → webhooks
        self._next_id = 100

    def _id(self):
        self._next_id += 1
        return str(self._next_id)

    def __call__(self, method, path, body):
        if method == "GET" and path == "/users/@me/guilds":
            return 200, [{"id": "G1", "name": "테스트서버"}]
        if method == "GET" and path == "/guilds/G1/channels":
            return 200, list(self.channels)
        if method == "POST" and path == "/guilds/G1/channels":
            if body["type"] == TYPE_FORUM and not self.forum_supported:
                return 400, {"code": 50024, "message": "forum not available"}
            ch = {"id": self._id(), "name": body["name"], "type": body["type"]}
            self.channels.append(ch)
            return 201, ch
        if method == "GET" and path.endswith("/webhooks"):
            channel_id = path.split("/")[2]
            return 200, self.webhooks.get(channel_id, [])
        if method == "POST" and path.endswith("/webhooks"):
            channel_id = path.split("/")[2]
            wh = {"id": self._id(), "token": f"tok-{channel_id}", "name": "AIM"}
            self.webhooks.setdefault(channel_id, []).append(wh)
            return 201, wh
        return 404, {}


def test_provision_creates_everything():
    api = FakeDiscordAPI()
    result = provision(DiscordAdmin("token", req_fn=api), "G1")

    assert len([c for c in api.channels if c["type"] == TYPE_CATEGORY]) == 1
    assert len([c for c in api.channels if c["type"] == TYPE_FORUM]) == 2   # 한국장·미국장
    assert len([c for c in api.channels if c["type"] == TYPE_TEXT]) == 3    # 시그널·포트폴리오·상담
    assert set(result.env_updates) == {
        "AIM_DISCORD_WEBHOOK_KR", "AIM_DISCORD_WEBHOOK_US", "AIM_DISCORD_WEBHOOK_SIGNALS",
        "AIM_DISCORD_WEBHOOK_PORTFOLIO", "AIM_DISCORD_WEBHOOK_CONSULT",
    }
    assert all(u.startswith("https://discord.com/api/webhooks/") for u in result.env_updates.values())
    assert result.warnings == []


def test_provision_idempotent_on_rerun():
    api = FakeDiscordAPI()
    admin = DiscordAdmin("token", req_fn=api)
    provision(admin, "G1")
    channels_after_first = len(api.channels)

    result2 = provision(admin, "G1")
    assert len(api.channels) == channels_after_first  # 중복 생성 없음
    assert result2.created == []
    assert len(result2.reused) >= 6  # 카테고리 + 채널 5 + 웹훅 5
    assert len(result2.env_updates) == 5  # URL은 여전히 반환 (재기록 안전)


def test_forum_falls_back_to_text():
    api = FakeDiscordAPI(forum_supported=False)
    result = provision(DiscordAdmin("token", req_fn=api), "G1")

    assert len([c for c in api.channels if c["type"] == TYPE_FORUM]) == 0
    assert len([c for c in api.channels if c["type"] == TYPE_TEXT]) == 5  # 전부 텍스트 폴백
    assert len(result.warnings) == 2  # 포럼 2개에 대한 폴백 경고
    assert len(result.env_updates) == 5  # 웹훅은 전부 발급됨


def test_bad_token_raises():
    def unauthorized(method, path, body):
        return 401, {"message": "401: Unauthorized"}

    with pytest.raises(RuntimeError, match="봇 토큰"):
        DiscordAdmin("bad", req_fn=unauthorized).list_guilds()


def test_update_env_file_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# 주석 유지\nAIM_DART_API_KEY=keep-me\nAIM_DISCORD_WEBHOOK_KR=old-url\n",
        encoding="utf-8",
    )
    changed = update_env_file(env, {
        "AIM_DISCORD_WEBHOOK_KR": "new-url",       # 교체
        "AIM_DISCORD_WEBHOOK_US": "added-url",     # 추가
    })
    text = env.read_text(encoding="utf-8")
    assert "# 주석 유지" in text and "AIM_DART_API_KEY=keep-me" in text  # 기존 보존
    assert "AIM_DISCORD_WEBHOOK_KR=new-url" in text and "old-url" not in text
    assert "AIM_DISCORD_WEBHOOK_US=added-url" in text
    assert set(changed) == {"AIM_DISCORD_WEBHOOK_KR", "AIM_DISCORD_WEBHOOK_US"}
