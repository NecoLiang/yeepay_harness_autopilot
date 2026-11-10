"""Drives tickets: Feishu message → Claude run → report → gate → PR → Feishu reply.

The engine decides what reaches people, never the model: an acknowledgement once, a question
when Claude needs a decision, a delivery only after the gate passes, and an honest blocker otherwise.
"""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Protocol

from . import protocol
from .claude import ClaudeRunner
from .config import Config
from .gate import run_gate
from .models import GateResult, Message, Report, Ticket, TicketState
from .store import Store, now
from .workspace import Workspace

LOG = logging.getLogger(__name__)
ACK = "收到，我会按 yeeHarness 流程处理，完成后在这个话题里给你 PR。"
MAX_REPAIRS = 2


class Channel(Protocol):
    def send(self, ticket: Ticket, text: str, key: str) -> None: ...


def new_ticket_id() -> str:
    return f"T{datetime.now():%m%d}-{uuid.uuid4().hex[:6]}"


def invitation(report: Report) -> str:
    rule = report.rule_proposal
    if rule is None:
        return ""
    return (f"\n另：本次可沉淀为业务规约 {rule.rule_id}「{rule.title}」，加入门禁后同类写法会被自动拦截，"
            f"回复「同意 {rule.rule_id}」即纳入。")


def minutes_since(start: str) -> float:
    return round((datetime.now().astimezone() - datetime.fromisoformat(start)).total_seconds() / 60, 1)


class Engine:
    def __init__(self, config: Config, store: Store, channel: Channel, runner: ClaudeRunner,
                 workspace: Workspace, gate=run_gate) -> None:
        self.config, self.store, self.channel = config, store, channel
        self.runner, self.workspace, self.gate = runner, workspace, gate
        self._pool = ThreadPoolExecutor(max_workers=config.max_workers, thread_name_prefix="ticket")
        self._active: set[str] = set()
        self._lock = threading.Lock()

    # ---------- intake ----------

    def open(self, message: Message) -> Ticket:
        stamp = now()
        ticket = self.store.create(Ticket(
            id=new_ticket_id(), thread_id=message.thread_id, chat_id=message.chat_id,
            origin_message_id=message.message_id, requester=message.sender_id, request=message.text,
            state=TicketState.QUEUED, session_id=str(uuid.uuid4()), created_at=stamp, updated_at=stamp))
        self.store.log(ticket.id, "request", sender=message.sender_id, text=message.text)
        return self._send(ticket, ACK, "ack")

    def follow_up(self, ticket: Ticket, message: Message) -> None:
        self.store.add_input(ticket.id, message.text)
        self.store.log(ticket.id, "human_message", sender=message.sender_id, text=message.text)

    def submit(self, ticket_id: str) -> Future[None] | None:
        """Runs the ticket in the pool unless it is already running; a running ticket picks up new inputs itself."""
        with self._lock:
            if ticket_id in self._active:
                return None
            self._active.add(ticket_id)
        return self._pool.submit(self._run_guarded, ticket_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)

    def _run_guarded(self, ticket_id: str) -> None:
        try:
            self.drive(ticket_id)
        finally:
            with self._lock:
                self._active.discard(ticket_id)
            if self.store.has_inputs(ticket_id):
                self.submit(ticket_id)

    # ---------- one ticket ----------

    def drive(self, ticket_id: str) -> Ticket:
        ticket = self._require(ticket_id)
        try:
            while True:
                inputs = self.store.take_inputs(ticket.id)
                if ticket.runs == 0:
                    prompt = protocol.first_prompt(
                        "\n".join([ticket.request, *inputs]), ticket.requester, self._report_path(ticket))
                elif inputs:
                    prompt = protocol.followup_prompt(inputs, self._report_path(ticket))
                else:
                    return ticket
                ticket = self._ensure_workspace(ticket)
                ticket, report = self._converse(ticket, prompt)
                ticket = self._settle(ticket, report)
        except Exception as error:  # noqa: BLE001 — any failure must reach the person who asked
            LOG.exception("ticket %s failed", ticket.id)
            ticket = self.store.save(self._require(ticket.id), state=TicketState.FAILED)
            self.store.log(ticket.id, "failed", error=repr(error)[:1000])
            return self._send(ticket, f"处理时出错，已停止并记录（{type(error).__name__}），需要人工查看。", "failed")

    def _require(self, ticket_id: str) -> Ticket:
        ticket = self.store.get(ticket_id)
        if ticket is None:
            raise KeyError(f"unknown ticket {ticket_id}")
        return ticket

    def _dir(self, ticket: Ticket) -> Path:
        return self.config.state_dir / "tickets" / ticket.id

    def _report_path(self, ticket: Ticket) -> Path:
        return self._dir(ticket) / "report.json"

    def _ensure_workspace(self, ticket: Ticket) -> Ticket:
        if ticket.worktree:
            return self.store.save(ticket, state=TicketState.WORKING)
        path, branch = self.workspace.prepare(ticket.id)
        return self.store.save(ticket, state=TicketState.WORKING, worktree=str(path), branch=branch)

    def _converse(self, ticket: Ticket, prompt: str) -> tuple[Ticket, Report]:
        """One Claude run, plus up to MAX_REPAIRS short runs if it ends without a valid report."""
        report_path = self._report_path(ticket)
        for attempt in range(MAX_REPAIRS + 1):
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.unlink(missing_ok=True)
            result = self.runner.run(Path(ticket.worktree), prompt, ticket.session_id, resume=ticket.runs > 0)
            ticket = self.store.save(ticket, runs=ticket.runs + 1, session_id=result.session_id)
            self.store.log(ticket.id, "claude_run", cost_usd=result.cost_usd, duration_ms=result.duration_ms,
                           turns=result.turns, is_error=result.is_error)
            try:
                return ticket, protocol.read_report(report_path)
            except protocol.ReportError as error:
                if attempt == MAX_REPAIRS:
                    raise
                prompt = protocol.repair_prompt(str(error), report_path)
        raise AssertionError("unreachable")

    def _settle(self, ticket: Ticket, report: Report) -> Ticket:
        rounds = 0
        gate: GateResult | None = None
        while report.state == "ready":
            problem = self._unpublishable(ticket)
            if problem is None:
                gate = self.gate(self.config.gate, Path(ticket.worktree), self.workspace.base_ref, self._dir(ticket),
                                 self.config.gate_test_cmd)
                self.store.log(ticket.id, "gate", verdict=gate.verdict, findings=list(gate.findings), round=rounds)
                if gate.verdict == "pass":
                    return self._deliver(ticket, report, gate)
                if gate.verdict == "error":
                    return self._block(ticket, report, "交付门禁无法运行，需要人工查看。", gate)
            if rounds >= self.config.max_gate_rounds:
                return self._block(ticket, report, "改动没能通过 yeeHarness 交付门禁，已保留为草稿，需要人工判断。", gate)
            rounds += 1
            path = self._report_path(ticket)
            prompt = protocol.gate_prompt(gate.markdown, path) if problem is None and gate else \
                protocol.repair_prompt(problem or "", path)
            ticket, report = self._converse(ticket, prompt)
        if report.state == "question":
            ticket = self.store.save(ticket, state=TicketState.WAITING, question=report.message)
            return self._send(ticket, report.message, "question")
        return self._block(ticket, report, report.message, gate)

    def _unpublishable(self, ticket: Ticket) -> str | None:
        path = Path(ticket.worktree)
        dirty = self.workspace.uncommitted(path)
        if dirty:
            return f"工作区还有未提交的改动：{', '.join(dirty[:5])}"
        if self.workspace.commits_ahead(path) == 0:
            return "分支上没有任何提交"
        return None

    def _deliver(self, ticket: Ticket, report: Report, gate: GateResult) -> Ticket:
        body = f"{report.pr_body}\n\n---\n\n{gate.markdown}"
        pr_url = self.workspace.publish(Path(ticket.worktree), ticket.branch, report.pr_title, body,
                                        draft=False, pr_url=ticket.pr_url)
        first = ticket.state != TicketState.READY and not ticket.pr_url
        ticket = self.store.save(ticket, state=TicketState.READY, pr_url=pr_url, question="")
        self.store.log(ticket.id, "delivered", pr_url=pr_url, minutes=minutes_since(ticket.created_at),
                       first=first, scenario=report.scenario)
        link = f" [查看 PR]({pr_url})" if pr_url else f"（本地分支 `{ticket.branch}`）"
        return self._send(ticket, f"{report.message}{link}{invitation(report)}", "delivery")

    def _block(self, ticket: Ticket, report: Report, text: str, gate: GateResult | None) -> Ticket:
        pr_url = ticket.pr_url
        if self._unpublishable(ticket) is None and report.pr_title:
            body = report.pr_body + (f"\n\n---\n\n{gate.markdown}" if gate else "")
            pr_url = self.workspace.publish(Path(ticket.worktree), ticket.branch, report.pr_title, body,
                                            draft=True, pr_url=ticket.pr_url)
        ticket = self.store.save(ticket, state=TicketState.BLOCKED, pr_url=pr_url)
        self.store.log(ticket.id, "blocked", reason=text)
        return self._send(ticket, text + (f" [草稿 PR]({pr_url})" if pr_url else ""), "blocked")

    def _send(self, ticket: Ticket, text: str, kind: str) -> Ticket:
        self.channel.send(ticket, text, f"{ticket.id}-{ticket.replies}")
        self.store.log(ticket.id, "bot_message", purpose=kind, text=text)
        return self.store.save(ticket, replies=ticket.replies + 1)
