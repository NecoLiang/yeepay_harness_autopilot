#!/usr/bin/env python3
"""Collects yeeHarness Autopilot run metrics from its own store (read-only).

Per ticket: minutes from the request to the first delivery, messages the bot sent, messages people
wrote after the request, Claude runs and cost, and how many times the gate sent work back. The
totals are the attention numbers the project is judged by.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path.home() / ".yeeharness-autopilot" / "autopilot.sqlite"


@dataclass(frozen=True)
class TicketMetrics:
    ticket_id: str
    title: str
    created_at: str
    state: str
    minutes_to_ready: float | None
    agent_messages: int
    human_messages: int
    claude_runs: int
    cost_usd: float
    gate_blocks: int
    pr_url: str


def ticket_metrics(ticket: dict[str, Any], events: list[dict[str, Any]]) -> TicketMetrics:
    delivered = [e for e in events if e["kind"] == "delivered"]
    return TicketMetrics(
        ticket_id=ticket["id"], title=ticket["request"][:60], created_at=ticket["created_at"], state=ticket["state"],
        minutes_to_ready=delivered[0]["minutes"] if delivered else None,
        agent_messages=sum(e["kind"] == "bot_message" for e in events),
        human_messages=sum(e["kind"] == "human_message" for e in events),
        claude_runs=sum(e["kind"] == "claude_run" for e in events),
        cost_usd=round(sum(e.get("cost_usd", 0) for e in events if e["kind"] == "claude_run"), 2),
        gate_blocks=sum(e["kind"] == "gate" and e.get("verdict") == "block" for e in events),
        pr_url=ticket.get("pr_url", ""))


def summarize(rows: list[TicketMetrics]) -> dict[str, Any]:
    ready = [t.minutes_to_ready for t in rows if t.minutes_to_ready is not None]
    count = len(rows)

    def per_ticket(values: list[float]) -> float | None:
        return round(sum(values) / count, 2) if count else None
    return {
        "tickets": count,
        "ready_or_done": len(ready),
        "states": {s: sum(t.state == s for t in rows) for s in sorted({t.state for t in rows})},
        "median_minutes_to_ready": statistics.median(ready) if ready else None,
        "agent_messages_per_ticket": per_ticket([t.agent_messages for t in rows]),
        "human_messages_per_ticket": per_ticket([t.human_messages for t in rows]),
        "cost_usd_per_ticket": per_ticket([t.cost_usd for t in rows]),
        "gate_blocks_total": sum(t.gate_blocks for t in rows),
    }


def collect(db: Path) -> dict[str, Any]:
    if not db.is_file():
        raise FileNotFoundError(f"no autopilot store at {db}")
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tickets = [json.loads(v) for (v,) in connection.execute("SELECT value FROM ticket ORDER BY rowid")]
        events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ticket_id, kind, detail in connection.execute("SELECT ticket_id, kind, detail FROM event ORDER BY seq"):
            events[ticket_id].append({"kind": kind, **json.loads(detail)})
    finally:
        connection.close()
    rows = [ticket_metrics(t, events[t["id"]]) for t in tickets]
    return {"collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "summary": summarize(rows), "tickets": [asdict(t) for t in rows]}


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
