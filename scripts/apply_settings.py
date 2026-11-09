#!/usr/bin/env python3
"""Configures a running dsh-superagent for yeeHarness Autopilot through its Management API.

Feishu is the only place work is requested; GitHub is where the agent delivers pull requests.
The script saves, in order: the GitHub Source, the Feishu Source, the Policy (Feishu allowed list,
an empty GitHub allowed list), the Executor (per-Ticket worktree) and the team prompts built by
``build_skills.py``. Each step is idempotent, so it can be re-run after fixing a refused save.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MARKER = "<!-- yeeharness-autopilot -->"
HEADERS = {"x-orchestrator-request": "1", "content-type": "application/json"}
RESTART_TIMEOUT_SECONDS = 120
POLL_SECONDS = 2
SECTION_KEYS = {"communication": "communication", "scope": "scope", "delivery": "delivery"}


class ApiError(Exception):
    """The Management API refused a request or could not be reached."""


@dataclass(frozen=True)
class Chat:
    chat_id: str
    name: str
    listen: str


@dataclass(frozen=True)
class Config:
    port: int
    repository: str
    github_cli: str
    feishu_cli: str
    chats: tuple[Chat, ...]
    sync_chat: str
    feishu_allowed: tuple[dict[str, str], ...]
    checkout: str
    max_workers: int


def _require(data: dict[str, Any], key: str, kind: type) -> Any:
    value = data.get(key)
    if not isinstance(value, kind) or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"config.{key} must be a non-empty {kind.__name__}")
    return value


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8"))
    repository = _require(data, "repository", str)
    if repository.count("/") != 1:
        raise ValueError("config.repository must look like owner/name")
    chats = tuple(Chat(_require(c, "chatId", str), _require(c, "name", str), c.get("listen", "mentions"))
                  for c in _require(data, "chats", list))
    if not chats or any(not c.chat_id.startswith("oc_") or c.listen not in ("mentions", "all") for c in chats):
        raise ValueError("config.chats needs at least one {chatId: 'oc_…', name, listen: mentions|all}")
    allowed = tuple(data.get("feishuAllowed", []))
    if any(not str(a.get("id", "")).startswith("ou_") for a in allowed):
        raise ValueError("config.feishuAllowed entries need an id starting with ou_")
    sync_chat = data.get("syncChat", chats[0].chat_id)
    for key in ("githubCli", "feishuCli", "checkout"):
        if not Path(_require(data, key, str)).expanduser().exists():
            raise ValueError(f"config.{key} does not exist: {data[key]}")
    return Config(int(data.get("port", 3082)), repository, str(Path(data["githubCli"]).expanduser()),
                  str(Path(data["feishuCli"]).expanduser()), chats, sync_chat, allowed,
                  str(Path(data["checkout"]).expanduser()), int(data.get("maxWorkers", 2)))


class Api:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}/orchestrator/api/"

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise ApiError(f"{method} {path} → {error.code}: {error.read().decode('utf-8', 'replace')}") from error
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            raise ApiError(f"{method} {path} unreachable: {error}") from error

    def wait_ready(self) -> None:
        deadline = time.monotonic() + RESTART_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                self.call("GET", "state")
                return
            except ApiError:
                time.sleep(POLL_SECONDS)
        raise ApiError("dsh-superagent did not come back after restart")

    def get(self, path: str) -> Any:
        """GET that tolerates the short window in which dsh-superagent restarts after a save."""
        deadline = time.monotonic() + RESTART_TIMEOUT_SECONDS
        while True:
            try:
                return self.call("GET", path)
            except ApiError as error:
                if "unreachable" not in str(error) or time.monotonic() > deadline:
                    raise
                time.sleep(max(POLL_SECONDS, 0.05))

    def save_block(self, block: str, value: Any) -> None:
        settings = self.get("settings")
        revision = _revision(settings, block)
        result = self.call("PUT", f"settings/{block}", {"value": value, "revision": revision})
        print(f"saved {block} (revision {result.get('revision')}){' — restarting' if result.get('restarting') else ''}")
        if result.get("restarting"):
            time.sleep(POLL_SECONDS)
            self.wait_ready()


def _revision(settings: dict[str, Any], block: str) -> int:
    if block.startswith("source:"):
        source_id = block.split(":", 1)[1]
        for source in settings.get("sources", []):
            if source.get("id") == source_id:
                return int(source.get("revision", 0))
        return 0
    return int(settings["blocks"][block]["revision"])


def prepare_command(checkout: str) -> str:
    """Per-Ticket worktree. Also refreshes origin/main, which the delivery gate diffs against."""
    repo = shlex.quote(checkout)
    return (f'git -C {repo} fetch --no-tags "https://github.com/$DSH_SUPERAGENT_GITHUB_REPOSITORY.git" '
            f'"+refs/heads/main:refs/remotes/origin/main" '
            f'"${{DSH_SUPERAGENT_GITHUB_PR_HEAD:-HEAD}}:refs/dsh-superagent/$DSH_SUPERAGENT_TICKET" && '
            f'git -C {repo} worktree add -b "agent/$DSH_SUPERAGENT_NAME" "$DSH_SUPERAGENT_DIR" '
            f'"refs/dsh-superagent/$DSH_SUPERAGENT_TICKET"')


def policy_value(current: dict[str, Any], config: Config) -> dict[str, Any]:
    sources = dict(current.get("sources", {}))
    sources["github"] = {**sources.get("github", {}), "allowed": []}
    feishu = {**sources.get("feishu", {}), "syncChat": config.sync_chat}
    if config.feishu_allowed:
        feishu["allowed"] = list(config.feishu_allowed)
    sources["feishu"] = feishu
    return {**current, "sources": sources}


def merge_section(current: str, addendum: str) -> str:
    base = current.split(MARKER, 1)[0].rstrip()
    return f"{base}\n\n{MARKER}\n{addendum.strip()}\n"


def prompt_config(current: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    sections = {key: merge_section(current.get(key, ""), package["sections"][name])
                for name, key in SECTION_KEYS.items()}
    skills = {**current.get("skills", {}), **package["skills"]}
    return {**current, **sections, "skills": skills}


def apply(api: Api, config: Config, package: dict[str, Any]) -> None:
    api.save_block("source:github", {"enabled": True, "config": {"repository": config.repository,
                                                                  "cli": config.github_cli}})
    api.save_block("source:feishu", {"enabled": True, "config": {
        "cli": config.feishu_cli, "directMessages": True, "otherChats": "none",
        "chats": [{"chatId": c.chat_id, "name": c.name, "listen": c.listen} for c in config.chats]}})
    settings = api.get("settings")
    api.save_block("policy", policy_value(settings["blocks"]["policy"]["value"], config))
    if not config.feishu_allowed:
        api.call("POST", "policy-sync/feishu", {})
        print("synced the Feishu allowed list from", config.sync_chat)
    executor = settings["blocks"]["executor"]["value"]
    api.save_block("executor", {**executor, "prepare": prepare_command(config.checkout),
                                "maxWorkers": config.max_workers})
    prompts = api.get("prompts")
    current = prompts["current"]
    result = api.call("PUT", "prompts", {"config": prompt_config(current["config"], package),
                                         "baseRevision": current["revision"]})
    print(f"saved prompts (revision {result.get('revision')}): skills {sorted(package['skills'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "autopilot.config.json"))
    parser.add_argument("--package", default=str(ROOT / "dist" / "prompts.json"))
    parser.add_argument("--prompts-only", action="store_true", help="only save the team prompts and skills")
    args = parser.parse_args(argv)
    try:
        package = json.loads(Path(args.package).read_text(encoding="utf-8"))
        if args.prompts_only:
            port = json.loads(Path(args.config).read_text(encoding="utf-8")).get("port", 3082)
            api = Api(int(port))
            current = api.call("GET", "prompts")["current"]
            result = api.call("PUT", "prompts", {"config": prompt_config(current["config"], package),
                                                 "baseRevision": current["revision"]})
            print(f"saved prompts (revision {result.get('revision')})")
            return 0
        config = load_config(Path(args.config))
        apply(Api(config.port), config, package)
    except (ValueError, OSError, ApiError, KeyError, json.JSONDecodeError) as error:
        print(f"[apply_settings] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
