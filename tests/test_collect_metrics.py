"""Tests for metrics collection from the autopilot store."""
from __future__ import annotations

from pathlib import Path

import pytest

import collect_metrics as metrics
from autopilot.models import Ticket, TicketState
from autopilot.store import Store


def make_ticket(tid: str, state: TicketState) -> Ticket:
    return Ticket(id=tid, thread_id=f"th-{tid}", chat_id="oc", origin_message_id="om", requester="ou",
                  request="分账差一分" * 20, state=state, session_id="s", created_at="2026-11-10T10:00:00+08:00",
                  updated_at="2026-11-10T10:00:00+08:00", pr_url="https://x/pr/1")


@pytest.mark.integration
def test_collect_counts_attention_and_cost(tmp_path: Path) -> None:
    store = Store(tmp_path / "a.sqlite")
    store.create(make_ticket("T1", TicketState.READY))
    store.create(make_ticket("T2", TicketState.WAITING))
    for kind, detail in [("bot_message", {}), ("claude_run", {"cost_usd": 1.25}), ("gate", {"verdict": "block"}),
                         ("claude_run", {"cost_usd": 0.75}), ("gate", {"verdict": "pass"}),
                         ("delivered", {"minutes": 12.5}), ("bot_message", {}), ("human_message", {})]:
        store.log("T1", kind, **detail)
    store.log("T2", "bot_message")
    store.close()
    data = metrics.collect(tmp_path / "a.sqlite")
    first = data["tickets"][0]
    assert (first["minutes_to_ready"], first["agent_messages"], first["human_messages"]) == (12.5, 2, 1)
    assert (first["claude_runs"], first["cost_usd"], first["gate_blocks"]) == (2, 2.0, 1)
    assert len(first["title"]) == 60
    summary = data["summary"]
    assert summary["tickets"] == 2 and summary["ready_or_done"] == 1 and summary["median_minutes_to_ready"] == 12.5
    assert summary["agent_messages_per_ticket"] == 1.5 and summary["gate_blocks_total"] == 1
    assert summary["states"] == {"ready": 1, "waiting": 1}


@pytest.mark.unit
def test_missing_store_fails_loudly(tmp_path: Path) -> None:
    assert metrics.main(["--db", str(tmp_path / "none.sqlite"), "--out", str(tmp_path / "m.json")]) == 1
