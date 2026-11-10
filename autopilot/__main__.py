"""Command line.

  python -m autopilot serve            # listen to Feishu and work on requests
  python -m autopilot ask "<需求>"      # local mode: same pipeline, replies printed instead of posted
  python -m autopilot reply <id> "<回复>"  # local mode: answer in a ticket's topic
  python -m autopilot status           # list tickets
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

from .admission import route
from .channels import ConsoleChannel, FeishuChannel
from .claude import ClaudeRunner
from .config import ROOT, Config, ConfigError, load_config
from .engine import Engine
from .feishu import FeishuError, LarkCli, parse_event
from .models import Message
from .store import Store, now
from .workspace import Workspace

LOG = logging.getLogger("autopilot")
LOCAL_CHAT = "local"
LOCAL_USER = "local-user"
RECONNECT_MAX_S = 60


def build(config: Config, channel) -> tuple[Store, Engine]:
    store = Store(config.state_dir / "autopilot.sqlite")
    return store, Engine(config, store, channel, ClaudeRunner(config), Workspace(config))


def local_message(text: str, thread: str | None = None) -> Message:
    message_id = f"local-{uuid.uuid4().hex[:8]}"
    return Message(message_id=message_id, chat_id=LOCAL_CHAT, thread_id=thread or message_id, sender_id=LOCAL_USER,
                   human=True, mentioned=True, direct=False, text=text, at=now())


def cmd_ask(config: Config, text: str) -> int:
    store, engine = build(config, ConsoleChannel(config.state_dir / "console.log"))
    ticket = engine.open(local_message(text))
    print(f"ticket {ticket.id}", flush=True)
    ticket = engine.drive(ticket.id)
    print(f"state {ticket.state.value} {ticket.pr_url or ticket.branch}")
    return 0


def cmd_reply(config: Config, ticket_id: str, text: str) -> int:
    store, engine = build(config, ConsoleChannel(config.state_dir / "console.log"))
    ticket = store.get(ticket_id)
    if ticket is None:
        print(f"unknown ticket {ticket_id}", file=sys.stderr)
        return 1
    engine.follow_up(ticket, local_message(text, ticket.thread_id))
    ticket = engine.drive(ticket.id)
    print(f"state {ticket.state.value} {ticket.pr_url or ticket.branch}")
    return 0


def cmd_status(config: Config) -> int:
    store = Store(config.state_dir / "autopilot.sqlite")
    for t in store.tickets():
        print(f"{t.id}  {t.state.value:8}  runs={t.runs}  {t.pr_url or t.branch}  {t.request[:40]}")
    return 0


def dispatch(raw: dict, bot_id: str, store: Store, engine: Engine, chats: frozenset[str],
             allowed: frozenset[str], direct_ok: bool) -> str:
    """Handles one Feishu event; returns the routing decision for logging and tests."""
    message = parse_event(raw, bot_id)
    if message is None or not store.first_sight(message.message_id):
        return "skip"
    decision = route(message, store, chats, allowed, direct_ok)
    LOG.info("%s %s: %s", message.message_id, decision.kind, decision.reason)
    if decision.kind == "new":
        engine.submit(engine.open(message).id)
    elif decision.kind == "followup" and decision.ticket:
        engine.follow_up(decision.ticket, message)
        engine.submit(decision.ticket.id)
    return decision.kind


def cmd_serve(config: Config) -> int:
    if config.feishu is None:
        print("serve needs a feishu section in the config", file=sys.stderr)
        return 1
    lark = LarkCli(config.feishu.cli)
    bot_id = lark.bot_id()
    allowed = frozenset(config.feishu.allowed) | (lark.members(config.feishu.sync_chat)
                                                   if config.feishu.sync_chat else frozenset())
    chats = frozenset(config.feishu.chats)
    store, engine = build(config, FeishuChannel(lark))
    LOG.info("listening: bot %s, %d chats, %d people allowed", bot_id, len(chats), len(allowed))
    for ticket in store.tickets():  # resume work interrupted by a restart
        if store.has_inputs(ticket.id):
            engine.submit(ticket.id)
    backoff = 1
    while True:
        started = time.monotonic()
        try:
            for raw in lark.events():
                dispatch(raw, bot_id, store, engine, chats, allowed, config.feishu.direct_messages)
        except FeishuError as error:
            LOG.warning("Feishu consumer stopped: %s", error)
        except KeyboardInterrupt:
            engine.shutdown()
            return 0
        backoff = 1 if time.monotonic() - started > 60 else min(backoff * 2, RECONNECT_MAX_S)
        time.sleep(backoff)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autopilot", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT / "autopilot.config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    ask = sub.add_parser("ask")
    ask.add_argument("text")
    reply = sub.add_parser("reply")
    reply.add_argument("ticket")
    reply.add_argument("text")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(Path(args.config))
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    if args.command == "serve":
        return cmd_serve(config)
    if args.command == "ask":
        return cmd_ask(config, args.text)
    if args.command == "reply":
        return cmd_reply(config, args.ticket, args.text)
    return cmd_status(config)


if __name__ == "__main__":
    sys.exit(main())
