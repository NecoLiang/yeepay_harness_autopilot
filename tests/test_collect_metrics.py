"""Tests for metrics collection from a dsh-superagent store."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import collect_metrics as metrics

T0 = "2026-11-10T10:00:00.000+08:00"


def ticket(tid: str, **extra: object) -> dict[str, object]:
    return {"id": tid, "title": f"t{tid}", "createdAt": T0, "channels": [{"source": "feishu"}],
            "assignments": [], "inputs": [], **extra}


def make_db(path: Path, tickets: list[dict[str, object]], outbox: list[dict[str, object]], decisions: list[str]) -> Path:
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE ticket (id TEXT, value TEXT); CREATE TABLE outbox (id TEXT, value TEXT);"
                     "CREATE TABLE decision (id TEXT, thread TEXT, value TEXT);")
    db.executemany("INSERT INTO ticket VALUES (?, ?)", [(t["id"], json.dumps(t)) for t in tickets])
    db.executemany("INSERT INTO outbox VALUES (?, ?)", [(str(i), json.dumps(o)) for i, o in enumerate(outbox)])
    db.executemany("INSERT INTO decision VALUES (?, '', ?)", [(str(i), json.dumps({"kind": k})) for i, k in enumerate(decisions)])
    db.commit()
    db.close()
    return path


@pytest.mark.unit
def test_ready_at_prefers_first_ready_report() -> None:
    t = ticket("1", assignments=[{"report": {"state": "ready", "at": "2026-11-10T10:30:00.000+08:00"}}],
               ended={"at": "2026-11-10T11:00:00.000+08:00", "outcome": "merged"})
    assert metrics.ready_at(t) == "2026-11-10T10:30:00.000+08:00"


@pytest.mark.unit
@pytest.mark.parametrize("extra, stage", [
    ({}, "queued"),
    ({"attention": {"question": "q"}}, "awaiting answer"),
    ({"assignments": [{"report": {"state": "progress", "at": T0}}]}, "progress"),
    ({"ended": {"at": T0, "outcome": "completed"}}, "ended"),
])
def test_stage_of(extra: dict[str, object], stage: str) -> None:
    assert metrics.stage_of(ticket("1", **extra)) == stage


@pytest.mark.integration
def test_collect_counts_attention(tmp_path: Path) -> None:
    done = ticket("1", ended={"at": "2026-11-10T10:42:00.000+08:00", "outcome": "completed"},
                  inputs=[{"kind": "trigger", "human": True}, {"kind": "trigger", "human": True, "context": True},
                          {"kind": "trigger"}], assignments=[{"id": "a"}])
    db = make_db(tmp_path / "s.sqlite", [done, ticket("2")],
                 [{"ticketId": "1", "status": "sent"}, {"ticketId": "1", "status": "pending"}, {"status": "sent"}],
                 ["accept", "accept", "ignore"])
    data = metrics.collect(db)
    first = data["tickets"][0]
    assert first["minutes_to_ready"] == 42.0
    assert first["human_messages"] == 1 and first["agent_messages"] == 1
    summary = data["summary"]
    assert summary["tickets"] == 2 and summary["ready_or_done"] == 1
    assert summary["decisions"] == {"accept": 2, "ignore": 1}
    assert summary["outcomes"] == {"completed": 1, "open": 1}


@pytest.mark.unit
def test_missing_store_fails_loudly(tmp_path: Path) -> None:
    assert metrics.main(["--db", str(tmp_path / "none.sqlite"), "--out", str(tmp_path / "m.json")]) == 1
