"""Configuration file loading and validation (``autopilot.config.json``)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWED_TOOLS = (
    "Read", "Edit", "Write", "Glob", "Grep", "Skill", "TodoWrite", "Task",
    "Bash(mvn *)", "Bash(./mvnw *)", "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)",
    "Bash(git add *)", "Bash(git commit *)", "Bash(git rev-parse*)", "Bash(git blame*)", "Bash(python3 *)",
    "Bash(java *)", "Bash(ls*)", "Bash(cat *)", "Bash(grep *)", "Bash(rg *)", "Bash(find *)", "Bash(wc *)",
    "Bash(head *)", "Bash(tail *)", "Bash(mkdir *)",
)
# Pushing, PRs and anything that talks to GitHub or Feishu stay with the orchestrator.
DISALLOWED_TOOLS = ("Bash(git push*)", "Bash(gh *)", "Bash(lark-cli *)", "Bash(curl *)", "WebFetch")


class ConfigError(ValueError):
    """The configuration file is missing a value or has an invalid one."""


@dataclass(frozen=True)
class FeishuConfig:
    cli: str
    chats: tuple[str, ...]
    direct_messages: bool
    sync_chat: str
    allowed: tuple[str, ...]


@dataclass(frozen=True)
class GithubConfig:
    cli: str
    repository: str


@dataclass(frozen=True)
class Config:
    state_dir: Path
    checkout: Path
    base_branch: str
    gate: Path
    claude_bin: str
    claude_model: str
    claude_timeout_s: int
    claude_budget_usd: float
    allowed_tools: tuple[str, ...]
    max_workers: int
    max_gate_rounds: int
    gate_test_cmd: str
    commit_name: str
    commit_email: str
    feishu: FeishuConfig | None
    github: GithubConfig | None


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty path")
    return Path(value).expanduser()


def _feishu(data: Any) -> FeishuConfig | None:
    if data is None:
        return None
    chats = tuple(data.get("chats", ()))
    if any(not isinstance(c, str) or not c.startswith("oc_") for c in chats):
        raise ConfigError("feishu.chats must be chat ids starting with oc_")
    allowed = tuple(data.get("allowed", ()))
    if any(not isinstance(a, str) or not a.startswith("ou_") for a in allowed):
        raise ConfigError("feishu.allowed must be open ids starting with ou_")
    sync_chat = data.get("syncChat", chats[0] if chats else "")
    if not chats and not data.get("directMessages", False):
        raise ConfigError("feishu needs at least one chat or directMessages: true")
    if not allowed and not sync_chat:
        raise ConfigError("feishu needs allowed open ids or a syncChat whose members may ask")
    return FeishuConfig(str(_path(data.get("cli"), "feishu.cli")), chats, bool(data.get("directMessages", False)),
                        sync_chat, allowed)


def _github(data: Any) -> GithubConfig | None:
    if data is None:
        return None
    repository = data.get("repository", "")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ConfigError("github.repository must look like owner/name")
    return GithubConfig(str(_path(data.get("cli"), "github.cli")), repository)


def _positive(data: dict[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{key} must be a positive number")
    return value


def load_config(path: Path) -> Config:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("config must be a JSON object")
    checkout = _path(data.get("checkout"), "checkout")
    if not (checkout / ".git").exists():
        raise ConfigError(f"checkout is not a git repository: {checkout}")
    tools = data.get("allowedTools", list(DEFAULT_ALLOWED_TOOLS))
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise ConfigError("allowedTools must be a list of strings")
    return Config(
        state_dir=_path(data.get("stateDir", str(Path.home() / ".yeeharness-autopilot")), "stateDir"),
        checkout=checkout,
        base_branch=str(data.get("baseBranch", "main")),
        gate=_path(data.get("gate", str(ROOT / "gate" / "yh_verify.py")), "gate"),
        claude_bin=str(data.get("claudeBin", "claude")),
        claude_model=str(data.get("claudeModel", "")),
        claude_timeout_s=int(_positive(data, "claudeTimeoutSeconds", 2400)),
        claude_budget_usd=float(_positive(data, "claudeBudgetUsd", 15)),
        allowed_tools=tuple(tools),
        max_workers=int(_positive(data, "maxWorkers", 2)),
        max_gate_rounds=int(_positive(data, "maxGateRounds", 2)),
        gate_test_cmd=str(data.get("gateTestCommand", "")),
        commit_name=str(data.get("commitName", "yeeHarness Autopilot")),
        commit_email=str(data.get("commitEmail", "autopilot@users.noreply.github.com")),
        feishu=_feishu(data.get("feishu")),
        github=_github(data.get("github")),
    )
