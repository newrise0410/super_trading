"""LLM 레이어 — MiniMax 파싱·<think> 제거, Codex CLI 커맨드 구성 검증 (외부 호출은 fake)."""

from pathlib import Path

import pytest

from aim.llm.codex_cli import CodexCLIClient
from aim.llm.minimax import MiniMaxClient


# ── MiniMax ───────────────────────────────────────────────────

def _mk_minimax(response_content, capture=None):
    def fake_post(url, headers, body):
        if capture is not None:
            capture.update({"url": url, "headers": headers, "body": body})
        return {"choices": [{"message": {"content": response_content}}]}

    return MiniMaxClient("key", "MiniMax-M2", post_fn=fake_post)


def test_minimax_basic_completion():
    capture = {}
    client = _mk_minimax("답변입니다", capture)
    assert client.complete("시스템", "질문") == "답변입니다"
    assert capture["url"] == "https://api.minimax.io/v1/chat/completions"
    assert capture["body"]["model"] == "MiniMax-M2"
    assert capture["body"]["messages"][0] == {"role": "system", "content": "시스템"}
    assert "Bearer key" in capture["headers"]["Authorization"]


def test_minimax_strips_think_block():
    client = _mk_minimax("<think>추론 과정...\n여러 줄</think>실제 답변")
    assert client.complete("s", "u") == "실제 답변"


def test_minimax_empty_response_raises():
    def empty_post(url, headers, body):
        return {"choices": []}

    client = MiniMaxClient("key", post_fn=empty_post)
    with pytest.raises(RuntimeError, match="빈 응답"):
        client.complete("s", "u")


def test_minimax_missing_key_rejected():
    with pytest.raises(ValueError):
        MiniMaxClient("")


# ── Codex CLI ─────────────────────────────────────────────────

def test_codex_builds_command_and_reads_output():
    captured = {}

    def fake_run(cmd, stdin_text):
        captured["cmd"] = cmd
        captured["stdin"] = stdin_text
        out_idx = cmd.index("-o") + 1
        Path(cmd[out_idx]).write_text("판정 결과", encoding="utf-8")
        return 0, ""

    client = CodexCLIClient(run_fn=fake_run)
    result = client.complete("시스템 프롬프트", "유저 프롬프트")

    assert result == "판정 결과"
    cmd = captured["cmd"]
    assert cmd[:2] == ["codex", "exec"]
    assert "-s" in cmd and "read-only" in cmd
    assert "--ephemeral" in cmd and "--skip-git-repo-check" in cmd
    assert cmd[-1] == "-"                       # 프롬프트는 stdin
    assert "-m" not in cmd                      # 모델 미지정 시 플래그 없음
    assert "시스템 프롬프트" in captured["stdin"] and "유저 프롬프트" in captured["stdin"]


def test_codex_model_flag_when_configured():
    def fake_run(cmd, stdin_text):
        Path(cmd[cmd.index("-o") + 1]).write_text("ok", encoding="utf-8")
        return 0, ""

    client = CodexCLIClient(model="gpt-5.5-codex", run_fn=fake_run)
    client.complete("s", "u")
    # run_fn 내부 검증 대신 재호출로 캡처
    captured = {}

    def capture_run(cmd, stdin_text):
        captured["cmd"] = cmd
        Path(cmd[cmd.index("-o") + 1]).write_text("ok", encoding="utf-8")
        return 0, ""

    CodexCLIClient(model="gpt-5.5-codex", run_fn=capture_run).complete("s", "u")
    idx = captured["cmd"].index("-m")
    assert captured["cmd"][idx + 1] == "gpt-5.5-codex"


def test_codex_nonzero_exit_raises():
    client = CodexCLIClient(run_fn=lambda cmd, s: (1, "login required"))
    with pytest.raises(RuntimeError, match="codex exec 실패"):
        client.complete("s", "u")
