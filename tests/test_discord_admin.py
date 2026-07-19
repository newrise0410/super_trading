"""discord-setup 프로비저닝 — 멀티 카테고리·재배치·멱등·포럼 폴백·.env 갱신 (API는 fake)."""

import pytest

from aim.delivery.discord_admin import (
    OLD_CATEGORY_NAME,
    TYPE_CATEGORY,
    TYPE_FORUM,
    TYPE_TEXT,
    DiscordAdmin,
    provision,
    update_env_file,
)

N_CATEGORIES, N_FORUM, N_TEXT, N_PRIVATE = 3, 2, 8, 4
N_CHANNELS = N_FORUM + N_TEXT  # 10


class FakeDiscordAPI:
    """길드/채널/웹훅 상태를 시뮬레이션하는 인메모리 Discord API."""

    def __init__(self, *, forum_supported=True):
        self.forum_supported = forum_supported
        self.channels: list[dict] = []
        self.webhooks: dict[str, list[dict]] = {}
        self.patches: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self._next_id = 100

    def _id(self):
        self._next_id += 1
        return str(self._next_id)

    def __call__(self, method, path, body):
        if method == "GET" and path == "/users/@me/guilds":
            return 200, [{"id": "G1", "name": "테스트서버"}]
        if method == "GET" and path == "/users/@me":
            return 200, {"id": "BOT1"}
        if method == "GET" and path == "/guilds/G1/channels":
            return 200, [dict(c) for c in self.channels]
        if method == "POST" and path == "/guilds/G1/channels":
            if body["type"] == TYPE_FORUM and not self.forum_supported:
                return 400, {"code": 50024, "message": "forum not available"}
            ch = {"id": self._id(), "name": body["name"], "type": body["type"],
                  "parent_id": body.get("parent_id")}
            self.channels.append(ch)
            return 201, ch
        if method == "PATCH" and path.startswith("/channels/"):
            cid = path.split("/")[2]
            self.patches.append((cid, body))
            ch = next((c for c in self.channels if c["id"] == cid), None)
            if ch and "parent_id" in body:
                ch["parent_id"] = body["parent_id"]
            return 200, {}
        if method == "DELETE" and path.startswith("/channels/"):
            cid = path.split("/")[2]
            self.deleted.append(cid)
            self.channels = [c for c in self.channels if c["id"] != cid]
            return 200, {}
        if method == "GET" and path.endswith("/webhooks"):
            return 200, self.webhooks.get(path.split("/")[2], [])
        if method == "POST" and path.endswith("/webhooks"):
            cid = path.split("/")[2]
            wh = {"id": self._id(), "token": f"tok-{cid}", "name": "AIM"}
            self.webhooks.setdefault(cid, []).append(wh)
            return 201, wh
        return 404, {}


def test_provision_creates_categories_and_channels():
    api = FakeDiscordAPI()
    result = provision(DiscordAdmin("token", req_fn=api), "G1")

    cats = [c for c in api.channels if c["type"] == TYPE_CATEGORY]
    assert [c["name"] for c in cats] == ["AIM 리포트", "AIM 시그널", "AIM 프라이빗"]
    assert len([c for c in api.channels if c["type"] == TYPE_FORUM]) == N_FORUM
    assert len([c for c in api.channels if c["type"] == TYPE_TEXT]) == N_TEXT
    assert len(result.env_updates) == N_CHANNELS
    assert result.warnings == []

    # 모든 채널이 올바른 카테고리 소속
    cat_ids = {c["name"]: c["id"] for c in cats}
    signal_channels = [c for c in api.channels if c.get("parent_id") == cat_ids["AIM 시그널"]]
    assert {c["name"] for c in signal_channels} == {"관심종목-시그널", "급등주", "공시", "긴급"}


def test_private_channels_get_permission_overwrites():
    api = FakeDiscordAPI()
    provision(DiscordAdmin("token", req_fn=api), "G1")

    perm_patches = [(cid, b) for cid, b in api.patches if "permission_overwrites" in b]
    assert len(perm_patches) == N_PRIVATE  # 포트폴리오·상담·ai-판단·전략-시뮬
    for _cid, body in perm_patches:
        everyone = next(o for o in body["permission_overwrites"] if o["id"] == "G1")
        bot = next(o for o in body["permission_overwrites"] if o["id"] == "BOT1")
        assert everyone["deny"] == "1024" and bot["allow"] == "3072"


def test_provision_idempotent_on_rerun():
    api = FakeDiscordAPI()
    admin = DiscordAdmin("token", req_fn=api)
    provision(admin, "G1")
    n_channels = len(api.channels)

    result2 = provision(admin, "G1")
    assert len(api.channels) == n_channels
    assert result2.created == []                       # 이동·생성·삭제 없음
    assert len(result2.env_updates) == N_CHANNELS


def test_migration_moves_channels_and_deletes_old_category():
    api = FakeDiscordAPI()
    # 구버전 상태: 단일 카테고리 아래 기존 채널
    old_cat = {"id": "OLD", "name": OLD_CATEGORY_NAME, "type": TYPE_CATEGORY, "parent_id": None}
    legacy = {"id": "CH1", "name": "한국장-브리핑", "type": TYPE_FORUM, "parent_id": "OLD"}
    api.channels += [old_cat, legacy]

    result = provision(DiscordAdmin("token", req_fn=api), "G1")

    moved = next(c for c in api.channels if c["id"] == "CH1")
    new_cat = next(c for c in api.channels if c["name"] == "AIM 리포트")
    assert moved["parent_id"] == new_cat["id"]          # 재배치됨
    assert "OLD" in api.deleted                          # 빈 구 카테고리 삭제
    assert any("이동" in x for x in result.created)
    assert any("삭제" in x for x in result.created)


def test_forum_falls_back_to_text():
    api = FakeDiscordAPI(forum_supported=False)
    result = provision(DiscordAdmin("token", req_fn=api), "G1")

    assert len([c for c in api.channels if c["type"] == TYPE_FORUM]) == 0
    assert len([c for c in api.channels if c["type"] == TYPE_TEXT]) == N_CHANNELS
    assert len(result.warnings) == N_FORUM
    assert len(result.env_updates) == N_CHANNELS


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
        "AIM_DISCORD_WEBHOOK_KR": "new-url",
        "AIM_DISCORD_WEBHOOK_US": "added-url",
    })
    text = env.read_text(encoding="utf-8")
    assert "# 주석 유지" in text and "AIM_DART_API_KEY=keep-me" in text
    assert "AIM_DISCORD_WEBHOOK_KR=new-url" in text and "old-url" not in text
    assert "AIM_DISCORD_WEBHOOK_US=added-url" in text
    assert set(changed) == {"AIM_DISCORD_WEBHOOK_KR", "AIM_DISCORD_WEBHOOK_US"}
