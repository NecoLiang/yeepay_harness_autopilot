"""Where the engine's messages go: the Feishu topic, or the console in local mode."""
from __future__ import annotations

import sys
from pathlib import Path

from .feishu import LarkCli
from .models import Ticket


class FeishuChannel:
    def __init__(self, lark: LarkCli) -> None:
        self.lark = lark

    def send(self, ticket: Ticket, text: str, key: str) -> None:
        self.lark.reply(ticket.origin_message_id, text, key)


class ConsoleChannel:
    """Local mode: prints what would be posted in the Feishu topic and keeps a transcript."""

    def __init__(self, transcript: Path) -> None:
        self.transcript = transcript
        transcript.parent.mkdir(parents=True, exist_ok=True)

    def send(self, ticket: Ticket, text: str, key: str) -> None:
        line = f"[飞书话题 {ticket.id}] 机器人：{text}"
        print(line, file=sys.stdout, flush=True)
        with self.transcript.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
