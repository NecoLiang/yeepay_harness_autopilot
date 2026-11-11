"""Adapter tests with fake executables: lark-cli, claude and gh, plus a real bare git remote."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from autopilot import __main__ as cli
from autopilot.claude import ClaudeError, ClaudeRunner
from autopilot.config import ROOT, Config, GithubConfig
from autopilot.engine import Engine
from autopilot.feishu import FeishuError, LarkCli
from autopilot.models import TicketState
from autopilot.store import Store
from autopilot.workspace import Workspace, WorkspaceError

FAKES = Path(__file__).resolve().parent / "fakes"
EVENT = {"message_id": "om_1", "chat_id": "oc_a", "chat_type": "group", "sender_id": "ou_u", "sender_type": "user",
         "content": "@_user_1 修一下分账", "create_time": "1794200000000",
         "mentions": [{"id": "ou_bot", "key": "@_user_1", "name": "助手"}]}


def demo(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    subprocess.run(["bash", str(ROOT / "scripts" / "init_demo_repo.sh"), str(checkout)], check=True,
                   capture_output=True)
    return checkout


def config(tmp_path: Path, checkout: Path, github: GithubConfig | None = None, claude: str = "") -> Config:
    return Config(state_dir=tmp_path / "state", checkout=checkout, base_branch="main", gate=ROOT / "gate" / "yh_verify.py",
                  claude_bin=claude or str(FAKES / "claude"), claude_model="", claude_timeout_s=60,
                  claude_budget_usd=1, allowed_tools=("Read",), max_workers=1, max_gate_rounds=1,
                  gate_test_cmd="true", commit_name="bot", commit_email="bot@example.com", feishu=None, github=github)


# ---------- lark-cli ----------

@pytest.fixture
def lark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LarkCli:
    monkeypatch.setenv("FAKE_LARK_LOG", str(tmp_path / "lark.log"))
    events = tmp_path / "events.ndjson"
    events.write_text(json.dumps(EVENT) + "\nnot json\n\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_LARK_EVENTS", str(events))
    return LarkCli(str(FAKES / "lark-cli"))


@pytest.mark.integration
def test_lark_bot_members_reply(lark: LarkCli, tmp_path: Path) -> None:
    assert lark.bot_id() == "ou_bot"
    assert lark.members("oc_a") == frozenset({"ou_u"})
    lark.reply("om_1", "好的", "T1-0")
    logged = (tmp_path / "lark.log").read_text(encoding="utf-8")
    assert "--message-id om_1" in logged and "--reply-in-thread" in logged and "T1-0" in logged


@pytest.mark.integration
def test_lark_events_yield_then_raise_on_exit(lark: LarkCli) -> None:
    seen = []
    with pytest.raises(FeishuError, match="consumer gone"):
        for raw in lark.events():
            seen.append(raw)
    assert seen == [EVENT]


@pytest.mark.integration
def test_lark_failure_is_an_error(lark: LarkCli) -> None:
    with pytest.raises(FeishuError, match="boom"):
        lark.run("fail", "now")


# ---------- claude subprocess + CLI commands ----------

@pytest.mark.integration
def test_cli_ask_reply_status_with_fake_claude(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    checkout = demo(tmp_path)
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checkout": str(checkout), "stateDir": str(tmp_path / "state"),
                                "claudeBin": str(FAKES / "claude"), "gateTestCommand": "true"}), encoding="utf-8")
    assert cli.main(["--config", str(path), "ask", "修分账"]) == 0
    out = capsys.readouterr().out
    assert "state ready" in out and "机器人：修好了" in out
    ticket_id = out.split("ticket ")[1].split()[0]
    assert cli.main(["--config", str(path), "reply", ticket_id, "谢谢"]) == 0
    assert cli.main(["--config", str(path), "reply", "T-none", "x"]) == 1
    assert cli.main(["--config", str(path), "status"]) == 0
    assert ticket_id in capsys.readouterr().out
    assert "机器人：" in (tmp_path / "state" / "console.log").read_text(encoding="utf-8")


@pytest.mark.integration
def test_cli_rejects_bad_config_and_serve_without_feishu(tmp_path: Path) -> None:
    assert cli.main(["--config", str(tmp_path / "missing.json"), "status"]) == 2
    checkout = demo(tmp_path)
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checkout": str(checkout), "stateDir": str(tmp_path / "s")}), encoding="utf-8")
    assert cli.main(["--config", str(path), "serve"]) == 1


@pytest.mark.integration
def test_claude_runner_errors(tmp_path: Path) -> None:
    broken = tmp_path / "claude"
    broken.write_text("#!/bin/sh\necho 'not logged in' >&2\nexit 1\n", encoding="utf-8")
    broken.chmod(0o755)
    runner = ClaudeRunner(config(tmp_path, tmp_path, claude=str(broken)))
    with pytest.raises(ClaudeError, match="not logged in"):
        runner.run(tmp_path, "p", "s", resume=False)
    missing = ClaudeRunner(config(tmp_path, tmp_path, claude=str(tmp_path / "nope")))
    with pytest.raises(ClaudeError, match="cannot start"):
        missing.run(tmp_path, "p", "s", resume=False)


# ---------- dispatch (serve loop body) ----------

class Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, ticket, text: str, key: str) -> None:
        self.sent.append(text)


@pytest.mark.integration
def test_dispatch_routes_new_followup_and_replays(tmp_path: Path) -> None:
    cfg = config(tmp_path, demo(tmp_path))
    store, channel = Store(cfg.state_dir / "s.sqlite"), Recorder()
    engine = Engine(cfg, store, channel, ClaudeRunner(cfg), Workspace(cfg))
    args = (store, engine, frozenset({"oc_a"}), frozenset({"ou_u"}), False)
    assert cli.dispatch(EVENT, "ou_bot", *args) == "new"
    assert cli.dispatch(EVENT, "ou_bot", *args) == "skip"  # replayed event
    followup = {**EVENT, "message_id": "om_2", "root_id": "om_1", "mentions": [], "content": "谢谢"}
    assert cli.dispatch(followup, "ou_bot", *args) == "followup"
    assert cli.dispatch({**EVENT, "message_id": "om_3", "sender_id": "ou_x"}, "ou_bot", *args) == "ignore"
    engine.shutdown()
    ticket = store.tickets()[0]
    assert ticket.state is TicketState.READY and channel.sent[0].startswith("收到")


# ---------- workspace publishing ----------

@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    checkout = demo(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(checkout), str(remote)], check=True)
    subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(checkout), "fetch", "-q", "origin"], check=True)
    monkeypatch.setenv("FAKE_GH_LOG", str(tmp_path / "gh.log"))
    cfg = config(tmp_path, checkout, GithubConfig(str(FAKES / "gh"), "agent/payment-demo"))
    return Workspace(cfg), remote, tmp_path / "gh.log"


@pytest.mark.integration
def test_publish_pushes_and_opens_then_updates_pr(published) -> None:
    workspace, remote, gh_log = published
    path, branch = workspace.prepare("T9")
    assert workspace.base_ref == "origin/main" and workspace.prepare("T9") == (path, branch)
    (path / "NOTE.md").write_text("x", encoding="utf-8")
    workspace.git(path, "add", ".")
    workspace.git(path, "commit", "-qm", "docs: note")
    assert workspace.commits_ahead(path) == 1 and workspace.uncommitted(path) == []
    url = workspace.publish(path, branch, "docs: note", "body", draft=True, pr_url="")
    assert url.endswith("/pull/1")
    assert "agent/T9" in subprocess.run(["git", "-C", str(remote), "branch"], capture_output=True, text=True).stdout
    assert workspace.publish(path, branch, "docs: note", "body2", draft=False, pr_url=url) == url
    calls = gh_log.read_text(encoding="utf-8")
    assert "pr create" in calls and "--draft" in calls and "pr edit" in calls and "pr ready" in calls


@pytest.mark.integration
def test_workspace_git_errors_are_reported(tmp_path: Path) -> None:
    workspace = Workspace(config(tmp_path, demo(tmp_path)))
    with pytest.raises(WorkspaceError, match="exited"):
        workspace.git(tmp_path, "rev-parse", "--verify", "no-such-ref")
    assert workspace.publish(tmp_path, "b", "t", "b", draft=False, pr_url="") == ""


@pytest.mark.integration
def test_claude_commits_use_configured_identity_not_global(tmp_path: Path) -> None:
    checkout = demo(tmp_path)
    cfg = config(tmp_path, checkout)
    store = Store(cfg.state_dir / "s.sqlite")
    engine = Engine(cfg, store, Recorder(), ClaudeRunner(cfg), Workspace(cfg))
    ticket = engine.drive(engine.open(cli.local_message("修")).id)
    author = subprocess.run(["git", "-C", ticket.worktree, "log", "-1", "--format=%an <%ae>|%cn <%ce>"],
                            capture_output=True, text=True).stdout.strip()
    assert author == "bot <bot@example.com>|bot <bot@example.com>"
