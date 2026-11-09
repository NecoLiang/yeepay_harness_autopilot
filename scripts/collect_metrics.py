#!/usr/bin/env python3
"""Collects yeeHarness Autopilot run metrics from the dsh-superagent store (read-only).

For every Ticket: how long it took from the Feishu request to a ready result, how many messages
the agent sent to people, how many times a person had to write, and how it ended. The totals are
the attention numbers the project is judged by: value delivered per unit of human attention.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path.home() / ".dsh" / "state" / "superagent" / "orchestrator.sqlite"


@dataclass(frozen=True)
class TicketMetrics:
    ticket_id: str
    title: str
    source: str
    created_at: str
    outcome: str
    stage: str
    minutes_to_ready: float | None
    agent_messages: int
    human_messages: int
    assignments: int
    open_question: bool


def minutes_between(start: str, end: str) -> float:
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60, 1)


def ready_at(ticket: dict[str, Any]) -> str | None:
    """The first time an Assignment reported ready, or when the Ticket ended completed or merged."""
    times = [a["report"]["at"] for a in ticket.get("assignments", [])
             if a.get("report", {}).get("state") == "ready"]
    ended = ticket.get("ended") or {}
    if ended.get("outcome") in ("completed", "merged"):
        times.append(ended["at"])
    return min(times) if times else None


def stage_of(ticket: dict[str, Any]) -> str:
    if ticket.get("ended"):
        return "ended"
    if ticket.get("attention"):
        return "awaiting answer"
    reports = [a.get("report", {}).get("state") for a in ticket.get("assignments", []) if a.get("report")]
    return reports[-1] if reports else "queued"


def ticket_metrics(ticket: dict[str, Any], sent_by_ticket: dict[str, int]) -> TicketMetrics:
    ready = ready_at(ticket)
    humans = [i for i in ticket.get("inputs", []) if i.get("kind") == "trigger" and i.get("human") and not i.get("context")]
    channels = ticket.get("channels") or [{}]
    return TicketMetrics(
        ticket_id=ticket["id"], title=ticket.get("title", ""), source=str(channels[0].get("source", "")),
        created_at=ticket["createdAt"], outcome=(ticket.get("ended") or {}).get("outcome", "open"),
        stage=stage_of(ticket), minutes_to_ready=minutes_between(ticket["createdAt"], ready) if ready else None,
        agent_messages=sent_by_ticket.get(ticket["id"], 0), human_messages=len(humans),
        assignments=len(ticket.get("assignments", [])), open_question=bool(ticket.get("attention")))


def summarize(tickets: list[TicketMetrics], decisions: dict[str, int]) -> dict[str, Any]:
    ready = [t.minutes_to_ready for t in tickets if t.minutes_to_ready is not None]
    count = len(tickets)
    return {
        "tickets": count,
        "ready_or_done": len(ready),
        "outcomes": {o: sum(t.outcome == o for t in tickets) for o in sorted({t.outcome for t in tickets})},
        "median_minutes_to_ready": statistics.median(ready) if ready else None,
        "agent_messages_per_ticket": round(sum(t.agent_messages for t in tickets) / count, 2) if count else None,
        "human_messages_per_ticket": round(sum(t.human_messages for t in tickets) / count, 2) if count else None,
        "decisions": decisions,
    }


def collect(db: Path) -> dict[str, Any]:
    if not db.is_file():
        raise FileNotFoundError(f"no dsh-superagent store at {db}")
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tickets = [json.loads(v) for (v,) in connection.execute("SELECT value FROM ticket")]
        sent: dict[str, int] = {}
        for (value,) in connection.execute("SELECT value FROM outbox"):
            receipt = json.loads(value)
            if receipt.get("status") == "sent" and receipt.get("ticketId"):
                sent[receipt["ticketId"]] = sent.get(receipt["ticketId"], 0) + 1
        decisions: dict[str, int] = {}
        for (value,) in connection.execute("SELECT value FROM decision"):
            kind = json.loads(value).get("kind", "unknown")
            decisions[kind] = decisions.get(kind, 0) + 1
    finally:
        connection.close()
    rows = sorted((ticket_metrics(t, sent) for t in tickets), key=lambda t: t.created_at)
    return {"collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "summary": summarize(rows, decisions), "tickets": [asdict(t) for t in rows]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(ROOT / "metrics" / "metrics.json"))
    args = parser.parse_args(argv)
    try:
        data = collect(Path(args.db))
    except (OSError, sqlite3.Error, json.JSONDecodeError, KeyError) as error:
        print(f"[collect_metrics] {error}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
