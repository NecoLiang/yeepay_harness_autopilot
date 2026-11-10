"""Feishu through ``lark-cli`` as the bot: live events, member lists and threaded replies.

Event shape follows what ``lark-cli event consume im.message.receive_v1`` prints, one JSON object
per line (the same contract dsh-superagent's Feishu Source relies on).
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from .models import Message

LOG = logging.getLogger(__name__)
QUIET = {"LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"}
COMMAND_TIMEOUT_S = 60
MAX_REPLY_CHARS = 1500


class FeishuError(RuntimeError):
    """lark-cli failed or printed something unexpected."""


def _time(value: str) -> str:
    if value.isdigit():
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    return value


def _text(content: str, mentions: list[dict[str, Any]], bot_id: str) -> str:
    """Replaces mention keys with names and drops the bot's own mention."""
    for mention in mentions:
        key = mention.get("key")
        if not key:
            continue
        name = "" if mention.get("id") == bot_id else f"@{mention.get('name', '')}"
        content = content.replace(key, name)
    return re.sub(r"\s+", " ", content).strip()


def parse_event(raw: dict[str, Any], bot_id: str) -> Message | None:
    """A normalized message, or None for the bot's own messages and malformed events."""
    try:
        sender = str(raw["sender_id"])
        if sender == bot_id:
            return None
        mentions = list(raw.get("mentions") or [])
        message_id, chat_id = str(raw["message_id"]), str(raw["chat_id"])
        return Message(
            message_id=message_id, chat_id=chat_id, thread_id=str(raw.get("root_id") or message_id),
            sender_id=sender, human=raw.get("sender_type") == "user",
            mentioned=any(m.get("id") == bot_id for m in mentions), direct=raw.get("chat_type") == "p2p",
            text=_text(str(raw.get("content", "")), mentions, bot_id), at=_time(str(raw.get("create_time", ""))))
    except (KeyError, TypeError, ValueError) as error:
        LOG.warning("skipping malformed Feishu event: %s", error)
        return None


class LarkCli:
    def __init__(self, cli: str) -> None:
        self.cli = cli
        self.env = {**os.environ, **QUIET}

    def run(self, *args: str) -> str:
        try:
            result = subprocess.run([self.cli, *args], capture_output=True, text=True, env=self.env,
                                    timeout=COMMAND_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise FeishuError(f"lark-cli {args[:2]} failed: {error}") from error
        if result.returncode != 0:
            raise FeishuError(f"lark-cli {args[:2]} exited {result.returncode}: {result.stderr.strip()[:500]}")
        return result.stdout

    def bot_id(self) -> str:
        line = self.run("api", "GET", "/open-apis/bot/v3/info", "--as", "bot", "--format", "ndjson").split("\n")[0]
        try:
            return str(json.loads(line)["bot"]["open_id"])
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise FeishuError(f"cannot read the bot's open_id: {line[:200]}") from error

    def members(self, chat_id: str) -> frozenset[str]:
        out = self.run("im", "+chat-members-list", "--chat-id", chat_id, "--member-types", "user",
                       "--page-all", "--page-limit", "0", "--as", "bot")
        try:
            data = json.loads(out[out.index("{"):])
        except (ValueError, json.JSONDecodeError) as error:
            raise FeishuError(f"cannot read members of {chat_id}") from error
        return frozenset(str(u["member_id"]) for u in data.get("users", []) if u.get("member_id"))

    def reply(self, message_id: str, text: str, key: str) -> None:
        """Replies in the topic of ``message_id``; Feishu keeps one reply per idempotency key."""
        self.run("im", "+messages-reply", "--message-id", message_id, "--markdown", text[:MAX_REPLY_CHARS],
                 "--reply-in-thread", "--idempotency-key", key, "--as", "bot")

    def events(self) -> Iterator[dict[str, Any]]:
        """Yields events until the consumer exits; raises FeishuError when it does."""
        process = subprocess.Popen([self.cli, "event", "consume", "im.message.receive_v1", "--as", "bot"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                                   text=True, env=self.env)
        assert process.stdout is not None
        try:
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    LOG.warning("skipping non-JSON event line: %s", line[:200])
        finally:
            process.terminate()
            stderr = process.stderr.read() if process.stderr else ""
            process.wait(timeout=10)
        raise FeishuError(f"event consumer exited {process.returncode}: {stderr.strip()[-500:]}")
