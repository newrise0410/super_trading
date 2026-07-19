"""딜리버리 — 메시지 분할·디스코드(일반/포럼 자동 감지) 검증 (HTTP는 fake 주입)."""

import pytest

from aim.delivery.discord import DiscordNotifier, PostResult
from aim.delivery.util import split_message

URL = "https://discord.com/api/webhooks/x/y"


def test_split_message_respects_limit_and_lines():
    text = "\n".join(f"line-{i:03d}" for i in range(100))  # 900자
    chunks = split_message(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks) == text  # 내용 손실 없음
    for c in chunks[:-1]:
        assert c.endswith("\n")  # 줄 경계에서만 분할


def test_split_message_short_text_single_chunk():
    assert split_message("short", 2000) == ["short"]


def _long_body():
    return "\n".join("한 줄짜리 본문입니다 " * 10 for _ in range(50))


# ── 일반 텍스트 채널 ──────────────────────────────────────────

def test_text_channel_sends_chunks_with_title_in_first():
    calls = []

    def fake_post(url, payload, params):
        calls.append((payload, params))
        return PostResult(200)

    n = DiscordNotifier(URL, post_fn=fake_post)
    assert n.send("테스트 제목", _long_body()) is True
    assert len(calls) >= 2  # 2000자 초과 → 분할
    first_payload, first_params = calls[0]
    assert first_payload["content"].startswith("## 테스트 제목")
    assert "thread_name" not in first_payload and first_params == {}
    assert all(p["username"] == "AIM 투자매니저" for p, _ in calls)
    assert all(len(p["content"]) <= 2000 for p, _ in calls)


def test_text_channel_failure_reported():
    n = DiscordNotifier(URL, post_fn=lambda u, p, q: PostResult(404))
    assert n.send("t", "b") is False


# ── 포럼 채널 자동 감지 ───────────────────────────────────────

def test_forum_detected_creates_post_then_threads_chunks():
    calls = []

    def fake_post(url, payload, params):
        calls.append((payload, params))
        if "thread_name" not in payload and "thread_id" not in params:
            return PostResult(400, error_code=220001)  # 포럼: thread_name 필수
        return PostResult(200, thread_id="THREAD-1")

    n = DiscordNotifier(URL, post_fn=fake_post)
    assert n.send("7/18 마감 브리핑", _long_body()) is True

    # 1콜: 일반 시도(400) → 2콜: thread_name으로 새 포스트 → 이후: thread_id로 이어 붙임
    assert "thread_name" not in calls[0][0]
    assert calls[1][0]["thread_name"] == "7/18 마감 브리핑"
    for payload, params in calls[2:]:
        assert params.get("thread_id") == "THREAD-1"
        assert "thread_name" not in payload


def test_forum_mode_cached_for_next_send():
    calls = []

    def fake_post(url, payload, params):
        calls.append((payload, params))
        if "thread_name" not in payload and "thread_id" not in params:
            return PostResult(400, error_code=220001)
        return PostResult(200, thread_id="T")

    n = DiscordNotifier(URL, post_fn=fake_post)
    n.send("첫 리포트", "본문")
    calls.clear()
    n.send("둘째 리포트", "본문")
    # 두 번째 발송은 감지 과정 없이 바로 thread_name으로 시작
    assert calls[0][0]["thread_name"] == "둘째 리포트"
    assert len(calls) == 1


def test_missing_url_rejected():
    with pytest.raises(ValueError):
        DiscordNotifier("")
