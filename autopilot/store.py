"""SQLite persistence: tickets, pending inputs, seen messages and an append-only event log.

The event log is what metrics are computed from: every message the bot sends, every message a
person writes, every Claude run and every gate run is one row.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Ticket, TicketState

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket (id TEXT PRIMARY KEY, thread_id TEXT UNIQUE NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS input (seq INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, text TEXT NOT NULL,
                                  taken INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS seen (message_id TEXT PRIMARY KEY, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event (seq INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, at TEXT NOT NULL,
                                  kind TEXT NOT NULL, detail TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ticket(value: str) -> Ticket:
    data = json.loads(value)
    return Ticket(**{**data, "state": TicketState(data["state"])})


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _write(self, sql: str, *args: Any) -> int:
        with self._lock:
            return self._db.execute(sql, args).rowcount

    def _rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def first_sight(self, message_id: str) -> bool:
        """True the first time a message id is seen; replays of the event stream return False."""
        return self._write("INSERT OR IGNORE INTO seen VALUES (?, ?)", message_id, now()) == 1

    def create(self, ticket: Ticket) -> Ticket:
        self._write("INSERT INTO ticket VALUES (?, ?, ?)", ticket.id, ticket.thread_id, self._json(ticket))
        return ticket

    def save(self, ticket: Ticket, **changes: Any) -> Ticket:
        updated = replace(ticket, **changes, updated_at=now())
        self._write("UPDATE ticket SET value = ? WHERE id = ?", self._json(updated), updated.id)
        return updated

    def get(self, ticket_id: str) -> Ticket | None:
        rows = self._rows("SELECT value FROM ticket WHERE id = ?", ticket_id)
        return _ticket(rows[0][0]) if rows else None

    def by_thread(self, thread_id: str) -> Ticket | None:
        rows = self._rows("SELECT value FROM ticket WHERE thread_id = ?", thread_id)
        return _ticket(rows[0][0]) if rows else None

    def tickets(self) -> list[Ticket]:
        return [_ticket(v) for (v,) in self._rows("SELECT value FROM ticket ORDER BY rowid")]

    def add_input(self, ticket_id: str, text: str) -> None:
        self._write("INSERT INTO input (ticket_id, text) VALUES (?, ?)", ticket_id, text)

    def take_inputs(self, ticket_id: str) -> list[str]:
        with self._lock:
            rows = self._db.execute("SELECT seq, text FROM input WHERE ticket_id = ? AND taken = 0 ORDER BY seq",
                                    (ticket_id,)).fetchall()
            self._db.executemany("UPDATE input SET taken = 1 WHERE seq = ?", [(seq,) for seq, _ in rows])
        return [text for _, text in rows]

    def has_inputs(self, ticket_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM input WHERE ticket_id = ? AND taken = 0 LIMIT 1", ticket_id))

    def log(self, ticket_id: str, kind: str, **detail: Any) -> None:
        self._write("INSERT INTO event (ticket_id, at, kind, detail) VALUES (?, ?, ?, ?)",
                    ticket_id, now(), kind, json.dumps(detail, ensure_ascii=False))

    def events(self, ticket_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT ticket_id, at, kind, detail FROM event" + (" WHERE ticket_id = ?" if ticket_id else "")
        rows = self._rows(sql + " ORDER BY seq", *([ticket_id] if ticket_id else []))
        return [{"ticket_id": t, "at": at, "kind": k, **json.loads(d)} for t, at, k, d in rows]

    @staticmethod
    def _json(ticket: Ticket) -> str:
        data = asdict(ticket)
        data["state"] = ticket.state.value
        return json.dumps(data, ensure_ascii=False)
