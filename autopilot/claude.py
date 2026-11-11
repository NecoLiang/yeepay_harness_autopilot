"""Runs Claude Code headless (``claude -p``) in a ticket's worktree.

Each ticket has one Claude session: the first run creates it with a fixed id, later runs resume it,
so a person's answer in Feishu continues the same conversation with all its context.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from .config import DISALLOWED_TOOLS, Config
from .models import RunResult

LOG = logging.getLogger(__name__)
SYSTEM_PROMPT = Path(__file__).resolve().parent / "prompts" / "system.md"


class ClaudeError(RuntimeError):
    """Claude Code could not be run, timed out, or printed no result."""


class ClaudeRunner:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.system_prompt = SYSTEM_PROMPT.read_text(encoding="utf-8")

    def command(self, session_id: str, resume: bool) -> list[str]:
        args = [self.config.claude_bin, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                "--max-budget-usd", str(self.config.claude_budget_usd),
                "--append-system-prompt", self.system_prompt,
                *(["--resume", session_id] if resume else ["--session-id", session_id]),
                *(["--model", self.config.claude_model] if self.config.claude_model else []),
                "--disallowedTools", *DISALLOWED_TOOLS,
                "--allowedTools", *self.config.allowed_tools]
        return args

    def env(self) -> dict[str, str]:
        """Claude's commits carry the configured identity, never the operator's global git identity."""
        name, email = self.config.commit_name, self.config.commit_email
        return {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}

    def run(self, cwd: Path, prompt: str, session_id: str, resume: bool) -> RunResult:
        """The prompt goes through stdin, so it never collides with the variadic tool flags."""
        try:
            result = subprocess.run(self.command(session_id, resume), cwd=cwd, input=prompt, capture_output=True,
                                    text=True, timeout=self.config.claude_timeout_s, env=self.env())
        except subprocess.TimeoutExpired as error:
            raise ClaudeError(f"Claude ran longer than {self.config.claude_timeout_s}s") from error
        except OSError as error:
            raise ClaudeError(f"cannot start {self.config.claude_bin}: {error}") from error
        return parse_result(result.stdout, result.stderr, session_id)


def parse_result(stdout: str, stderr: str, session_id: str) -> RunResult:
    try:
        data = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise ClaudeError(f"Claude printed no JSON result: {(stderr or stdout).strip()[-500:]}") from error
    return RunResult(session_id=str(data.get("session_id") or session_id), text=str(data.get("result", "")),
                     is_error=bool(data.get("is_error", False)), cost_usd=float(data.get("total_cost_usd") or 0),
                     duration_ms=int(data.get("duration_ms") or 0), turns=int(data.get("num_turns") or 0))
