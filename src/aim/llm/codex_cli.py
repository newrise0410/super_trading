"""Codex CLI 백엔드 — `codex exec` 서브프로세스 (딥씽킹 티어).

ChatGPT 구독 OAuth를 Codex CLI가 의도된 방식으로 사용 — 토큰 갱신도 CLI가 담당.
- 프롬프트는 stdin으로 전달 (Windows 명령줄 길이 제한 회피)
- 결과는 --output-last-message 파일로 수신 (stdout 로그와 분리)
- read-only 샌드박스 + --ephemeral (세션 기록 없음) — 순수 텍스트 생성용
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 300

RunFn = Callable[[list[str], str], tuple[int, str]]
# (cmd, stdin_text) -> (returncode, stderr_tail)


def codex_available() -> bool:
    return shutil.which("codex") is not None


def _default_run(cmd: list[str], stdin_text: str) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, input=stdin_text, capture_output=True, text=True,
        encoding="utf-8", timeout=_TIMEOUT_SEC,
    )
    return proc.returncode, (proc.stderr or "")[-500:]


class CodexCLIClient:
    name = "codex"

    def __init__(self, model: str = "", *, run_fn: RunFn | None = None) -> None:
        self.model = model or "(codex-default)"
        self._model_flag = model
        self._run = run_fn or _default_run

    def complete(self, system: str, user: str) -> str:
        prompt = f"{system}\n\n---\n\n{user}"
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "last_message.txt"
            cmd = [
                "codex", "exec",
                "-s", "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "-o", str(out_file),
            ]
            if self._model_flag:
                cmd += ["-m", self._model_flag]
            cmd.append("-")  # 프롬프트는 stdin

            code, stderr_tail = self._run(cmd, prompt)
            if code != 0:
                raise RuntimeError(f"codex exec 실패 (exit {code}): {stderr_tail}")
            if not out_file.is_file():
                raise RuntimeError("codex exec 결과 파일 없음")
            return out_file.read_text(encoding="utf-8").strip()
