"""Domain records. All are immutable; changes go through ``dataclasses.replace``."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TicketState(str, Enum):
    QUEUED = "queued"
    WORKING = "working"
    WAITING = "waiting"  # a person must answer a question
    READY = "ready"  # delivered; a person reviews the PR
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class Message:
    """One Feishu message, already normalized."""

    message_id: str
    chat_id: str
    thread_id: str  # the root message of its topic, or itself
    sender_id: str
    human: bool
    mentioned: bool
    direct: bool
    text: str
    at: str


@dataclass(frozen=True)
class Ticket:
    id: str
    thread_id: str
    chat_id: str
    origin_message_id: str
    requester: str
    request: str
    state: TicketState
    session_id: str
    created_at: str
    updated_at: str
    branch: str = ""
    worktree: str = ""
    pr_url: str = ""
    question: str = ""
    replies: int = 0
    runs: int = 0


@dataclass(frozen=True)
class RuleProposal:
    rule_id: str
    title: str


@dataclass(frozen=True)
class Report:
    """What a Claude run hands back through its report file."""

    state: str  # ready | question | blocked
    message: str
    scenario: str = ""
    pr_title: str = ""
    pr_body: str = ""
    rule_proposal: RuleProposal | None = None


@dataclass(frozen=True)
class RunResult:
    session_id: str
    text: str
    is_error: bool
    cost_usd: float
    duration_ms: int
    turns: int


@dataclass(frozen=True)
class GateResult:
    verdict: str  # pass | block | error
    markdown: str
    findings: tuple[str, ...] = field(default_factory=tuple)
