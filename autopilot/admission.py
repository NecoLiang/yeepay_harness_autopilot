"""Who may start work and which messages continue existing work (borrowed from dsh-superagent's gate).

- New work: a person, in a configured chat (or a direct message when enabled), who mentions the bot
  and is on the allowed list.
- A follow-up: a person on the allowed list writing in the topic of an existing ticket; no mention needed.
- Everything else is ignored silently: the bot speaks only when someone must act or can use a result.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Message, Ticket
from .store import Store


@dataclass(frozen=True)
class Route:
    kind: str  # new | followup | ignore
    reason: str
    ticket: Ticket | None = None


def route(message: Message, store: Store, chats: frozenset[str], allowed: frozenset[str], direct_ok: bool) -> Route:
    if not message.human:
        return Route("ignore", "not a person")
    if message.chat_id not in chats and not (message.direct and direct_ok):
        return Route("ignore", "chat not configured")
    if message.sender_id not in allowed:
        return Route("ignore", "sender not on the allowed list")
    if not message.text:
        return Route("ignore", "empty message")
    ticket = store.by_thread(message.thread_id)
    if ticket is not None:
        return Route("followup", "message in a ticket's topic", ticket)
    if not (message.mentioned or message.direct):
        return Route("ignore", "bot not addressed")
    return Route("new", "addressed request from an allowed person")
