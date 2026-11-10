"""End-to-end engine tests: real git worktrees, the real gate, a scripted stand-in for Claude."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

from autopilot.config import ROOT, Config
from autopilot.engine import ACK, Engine
from autopilot.models import RunResult, Ticket, TicketState
from autopilot.store import Store
from autopilot.workspace import Workspace
from autopilot.__main__ import local_message

CALC = "src/main/java/com/yeepay/demo/split/SplitCalculator.java"
TEST = "src/test/java/com/yeepay/demo/split/SplitCalculatorTest.java"
Step = Callable[[Path, Path], None]


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", *args], cwd=cwd, check=True,
                   capture_output=True)


def edit_and_commit(path: str, old: str, new: str) -> Callable[[Path], None]:
    def apply(cwd: Path) -> None:
        file = cwd / path
        file.write_text(file.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        git(cwd, "commit", "-qam", "fix: change")
    return apply


def report(state: str, message: str, **extra: object) -> Callable[[Path], None]:
    def write(path: Path) -> None:
        body = {"state": state, "message": message, **extra}
        if state == "ready":
            body = {"pr_title": "fix: split", "pr_body": "## 背景\n...", "scenario": "缺陷修复", **body}
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return write


def step(*actions: Callable[[Path], None], writes: Callable[[Path], None] | None = None) -> Step:
    def run(cwd: Path, report_path: Path) -> None:
        for action in actions:
            action(cwd)
        if writes:
            writes(report_path)
    return run


@dataclass
class FakeClaude:
    steps: list[Step]
    calls: list[tuple[str, bool]] = field(default_factory=list)

    def run(self, cwd: Path, prompt: str, session_id: str, resume: bool) -> RunResult:
        self.calls.append((prompt, resume))
        report_path = Path(prompt.split("`")[-2])
        self.steps.pop(0)(cwd, report_path)
        return RunResult(session_id, "done", False, 0.5, 1000, 3)


@dataclass
class Recorder:
    sent: list[tuple[str, str]] = field(default_factory=list)

    def send(self, ticket: Ticket, text: str, key: str) -> None:
        self.sent.append((key, text))


@pytest.fixture
def setup(tmp_path: Path):
    checkout = tmp_path / "checkout"
    subprocess.run(["bash", str(ROOT / "scripts" / "init_demo_repo.sh"), str(checkout)], check=True,
                   capture_output=True)
    config = Config(state_dir=tmp_path / "state", checkout=checkout, base_branch="main", gate=ROOT / "gate" / "yh_verify.py",
                    claude_bin="claude", claude_model="", claude_timeout_s=60, claude_budget_usd=1, allowed_tools=(),
                    max_workers=1, max_gate_rounds=2, gate_test_cmd="true", commit_name="bot",
                    commit_email="bot@example.com", feishu=None, github=None)
    store = Store(config.state_dir / "s.sqlite")

    def make(steps: list[Step]) -> tuple[Engine, FakeClaude, Recorder]:
        claude, channel = FakeClaude(steps), Recorder()
        return Engine(config, store, channel, claude, Workspace(config)), claude, channel
    return store, make


GOOD = edit_and_commit(CALC, "double total = orderAmount.doubleValue();",
                       "BigDecimal total = orderAmount; // fixed")
BAD = edit_and_commit(TEST, "class SplitCalculatorTest {", "class SplitCalculatorTest {\n    // TODO more cases")


@pytest.mark.integration
def test_happy_path_acks_once_and_delivers_after_gate(setup) -> None:
    store, make = setup
    engine, claude, channel = make([step(GOOD, writes=report("ready", "分账合计已与订单金额一致"))])
    ticket = engine.open(local_message("分账差一分"))
    ticket = engine.drive(ticket.id)
    assert ticket.state is TicketState.READY
    assert [text for _, text in channel.sent] == [ACK, "分账合计已与订单金额一致（本地分支 `agent/%s`）" % ticket.id]
    assert claude.calls[0][1] is False
    kinds = [e["kind"] for e in store.events(ticket.id)]
    assert kinds == ["request", "bot_message", "claude_run", "gate", "delivered", "bot_message"]


@pytest.mark.integration
def test_gate_block_is_sent_back_to_claude_not_to_people(setup) -> None:
    store, make = setup
    engine, claude, channel = make([
        step(BAD, writes=report("ready", "好了")),
        step(edit_and_commit(TEST, "    // TODO more cases\n", ""), GOOD, writes=report("ready", "修好了")),
    ])
    ticket = engine.drive(engine.open(local_message("修")).id)
    assert ticket.state is TicketState.READY
    assert "交付门禁没有通过" in claude.calls[1][0] and "G-003" in claude.calls[1][0]
    assert claude.calls[1][1] is True
    assert len(channel.sent) == 2
    assert [e["verdict"] for e in store.events(ticket.id) if e["kind"] == "gate"] == ["block", "pass"]


@pytest.mark.integration
def test_gate_rounds_exhausted_blocks_honestly(setup) -> None:
    store, make = setup
    engine, _, channel = make([step(BAD, writes=report("ready", "好了"))] +
                              [step(writes=report("ready", "好了")) for _ in range(2)])
    ticket = engine.drive(engine.open(local_message("修")).id)
    assert ticket.state is TicketState.BLOCKED
    assert "没能通过" in channel.sent[-1][1]


@pytest.mark.integration
def test_question_waits_then_answer_resumes_same_session(setup) -> None:
    store, make = setup
    engine, claude, channel = make([
        step(writes=report("question", "尾差给谁？A. 最后一方（推荐）B. 平台")),
        step(GOOD, writes=report("ready", "已按 A 修复", rule_proposal={"id": "R-001", "title": "尾差显式分配"})),
    ])
    ticket = engine.drive(engine.open(local_message("修")).id)
    assert ticket.state is TicketState.WAITING and channel.sent[-1][1].startswith("尾差给谁")
    engine.follow_up(ticket, local_message("A", ticket.thread_id))
    ticket = engine.drive(ticket.id)
    assert ticket.state is TicketState.READY
    assert "> A" in claude.calls[1][0] and claude.calls[1][1] is True
    assert "回复「同意 R-001」" in channel.sent[-1][1]
    assert len({key for key, _ in channel.sent}) == len(channel.sent)


@pytest.mark.integration
def test_missing_report_is_repaired_then_uncommitted_work_is_sent_back(setup) -> None:
    store, make = setup

    def dirty(cwd: Path) -> None:
        (cwd / "NOTES.md").write_text("x", encoding="utf-8")

    def clean(cwd: Path) -> None:
        (cwd / "NOTES.md").unlink()

    engine, claude, _ = make([
        step(),  # wrote no report
        step(dirty, GOOD, writes=report("ready", "好")),
        step(clean, writes=report("ready", "好")),
    ])
    ticket = engine.drive(engine.open(local_message("修")).id)
    assert ticket.state is TicketState.READY
    assert "no report file" in claude.calls[1][0]
    assert "未提交的改动" in claude.calls[2][0]


@pytest.mark.integration
def test_crash_is_reported_not_swallowed(setup) -> None:
    store, make = setup

    def boom(cwd: Path, report_path: Path) -> None:
        raise RuntimeError("claude exploded")

    engine, _, channel = make([boom])
    ticket = engine.drive(engine.open(local_message("修")).id)
    assert ticket.state is TicketState.FAILED
    assert "出错" in channel.sent[-1][1]
    assert any(e["kind"] == "failed" and "exploded" in e["error"] for e in store.events(ticket.id))


@pytest.mark.integration
def test_submit_runs_in_pool_and_does_not_double_run(setup) -> None:
    store, make = setup
    engine, claude, _ = make([step(GOOD, writes=report("ready", "好"))])
    ticket = engine.open(local_message("修"))
    future = engine.submit(ticket.id)
    assert engine.submit(ticket.id) is None
    future.result(timeout=60)
    engine.shutdown()
    assert len(claude.calls) == 1 and store.get(ticket.id).state is TicketState.READY
