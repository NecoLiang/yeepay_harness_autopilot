"""Unit tests for admission, Feishu parsing, store, protocol, Claude invocation, config and rule merging."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from autopilot import protocol
from autopilot.admission import route
from autopilot.claude import ClaudeError, ClaudeRunner, parse_result
from autopilot.config import ConfigError, load_config
from autopilot.feishu import parse_event
from autopilot.gate import merged_rules
from autopilot.models import Message, Ticket, TicketState
from autopilot.store import Store

BOT = "ou_bot"


def msg(**kw: object) -> Message:
    base = dict(message_id="om_1", chat_id="oc_a", thread_id="om_1", sender_id="ou_u", human=True, mentioned=True,
                direct=False, text="修 bug", at="t")
    return Message(**{**base, **kw})


def ticket(thread: str = "om_root") -> Ticket:
    return Ticket(id="T1", thread_id=thread, chat_id="oc_a", origin_message_id=thread, requester="ou_u", request="r",
                  state=TicketState.READY, session_id="s", created_at="2026-11-10T10:00:00+08:00",
                  updated_at="2026-11-10T10:00:00+08:00")


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "s.sqlite")


# ---------- admission ----------

CHATS, ALLOWED = frozenset({"oc_a"}), frozenset({"ou_u"})


@pytest.mark.unit
@pytest.mark.parametrize("kw, kind, reason", [
    ({}, "new", "addressed"),
    ({"human": False}, "ignore", "not a person"),
    ({"chat_id": "oc_other"}, "ignore", "chat"),
    ({"sender_id": "ou_stranger"}, "ignore", "allowed"),
    ({"mentioned": False}, "ignore", "not addressed"),
    ({"text": ""}, "ignore", "empty"),
    ({"chat_id": "oc_dm", "direct": True, "mentioned": False}, "new", "addressed"),
])
def test_route_new_work(store: Store, kw: dict, kind: str, reason: str) -> None:
    decision = route(msg(**kw), store, CHATS, ALLOWED, direct_ok=True)
    assert decision.kind == kind and reason in decision.reason


@pytest.mark.unit
def test_route_followup_needs_no_mention_but_needs_allowed_sender(store: Store) -> None:
    store.create(ticket("om_root"))
    assert route(msg(thread_id="om_root", mentioned=False), store, CHATS, ALLOWED, False).kind == "followup"
    assert route(msg(thread_id="om_root", sender_id="ou_x"), store, CHATS, ALLOWED, False).kind == "ignore"


@pytest.mark.unit
def test_direct_messages_off(store: Store) -> None:
    assert route(msg(chat_id="oc_dm", direct=True), store, CHATS, ALLOWED, direct_ok=False).kind == "ignore"


# ---------- feishu ----------

EVENT = {"message_id": "om_2", "chat_id": "oc_a", "chat_type": "group", "sender_id": "ou_u", "sender_type": "user",
         "content": "@_user_1 分账 @_user_2 看下", "create_time": "1794200000000", "root_id": "om_root",
         "mentions": [{"id": BOT, "key": "@_user_1", "name": "助手"}, {"id": "ou_z", "key": "@_user_2", "name": "张三"}]}


@pytest.mark.unit
def test_parse_event_normalizes_mentions_and_thread() -> None:
    message = parse_event(EVENT, BOT)
    assert message is not None
    assert message.text == "分账 @张三 看下" and message.mentioned and message.thread_id == "om_root"
    assert message.at.startswith("2026-")


@pytest.mark.unit
def test_parse_event_skips_own_and_malformed() -> None:
    assert parse_event({**EVENT, "sender_id": BOT}, BOT) is None
    assert parse_event({"chat_id": "x"}, BOT) is None
    top = parse_event({k: v for k, v in EVENT.items() if k != "root_id"}, BOT)
    assert top is not None and top.thread_id == "om_2"


# ---------- store ----------

@pytest.mark.unit
def test_store_roundtrip_inputs_and_dedupe(store: Store) -> None:
    t = store.create(ticket())
    saved = store.save(t, state=TicketState.WAITING, question="q")
    assert store.get("T1") == saved and t.state is TicketState.READY
    assert store.by_thread("om_root") == saved
    store.add_input("T1", "a")
    store.add_input("T1", "b")
    assert store.has_inputs("T1") and store.take_inputs("T1") == ["a", "b"] and store.take_inputs("T1") == []
    assert store.first_sight("om_9") and not store.first_sight("om_9")
    store.log("T1", "gate", verdict="pass")
    assert store.events("T1")[0]["verdict"] == "pass" and store.tickets() == [saved]


# ---------- protocol ----------

def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.unit
def test_read_report_ready_with_rule(tmp_path: Path) -> None:
    report = protocol.read_report(write(tmp_path, {"state": "ready", "message": "好", "pr_title": "fix: x",
                                                   "pr_body": "b", "rule_proposal": {"id": "R-001", "title": "t"}}))
    assert report.rule_proposal is not None and report.rule_proposal.rule_id == "R-001"


@pytest.mark.unit
@pytest.mark.parametrize("data, error", [
    ({"state": "done", "message": "x"}, "state"),
    ({"state": "ready", "message": "x"}, "pr_title"),
    ({"state": "question", "message": ""}, "message"),
    ({"state": "question", "message": "x" * 401}, "longer"),
    ({"state": "question", "message": 3}, "string"),
    ({"state": "blocked", "message": "x", "rule_proposal": "R-1"}, "object"),
])
def test_read_report_rejects(tmp_path: Path, data: dict, error: str) -> None:
    with pytest.raises(protocol.ReportError, match=error):
        protocol.read_report(write(tmp_path, data))


@pytest.mark.unit
def test_read_report_missing_and_invalid(tmp_path: Path) -> None:
    with pytest.raises(protocol.ReportError, match="no report"):
        protocol.read_report(tmp_path / "none.json")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(protocol.ReportError, match="JSON"):
        protocol.read_report(tmp_path / "bad.json")


@pytest.mark.unit
def test_prompts_carry_report_path() -> None:
    path = Path("/x/report.json")
    for text in (protocol.first_prompt("r", "u", path), protocol.followup_prompt(["a"], path),
                 protocol.gate_prompt("md", path), protocol.repair_prompt("p", path)):
        assert text.split("`")[-2] == str(path)


# ---------- claude ----------

@pytest.mark.unit
def test_parse_result_and_errors() -> None:
    out = json.dumps({"session_id": "s2", "result": "ok", "is_error": False, "total_cost_usd": 0.17,
                      "duration_ms": 3900, "num_turns": 1})
    result = parse_result("noise\n" + out, "", "s1")
    assert (result.session_id, result.cost_usd, result.turns) == ("s2", 0.17, 1)
    with pytest.raises(ClaudeError, match="no JSON"):
        parse_result("", "auth failed", "s1")


# ---------- config ----------

def config_file(tmp_path: Path, **extra: object) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checkout": str(repo), "stateDir": str(tmp_path / "st"), **extra}), encoding="utf-8")
    return path


@pytest.mark.unit
def test_config_defaults_and_local_mode(tmp_path: Path) -> None:
    config = load_config(config_file(tmp_path))
    assert config.feishu is None and config.github is None and config.max_gate_rounds == 2
    command = ClaudeRunner(config).command("sid", resume=False)
    assert command[:2] == [config.claude_bin, "-p"] and "--session-id" in command
    assert command.index("--disallowedTools") < command.index("--allowedTools")
    assert "Bash(git push*)" in command and "--resume" in ClaudeRunner(config).command("sid", resume=True)


@pytest.mark.unit
@pytest.mark.parametrize("extra, error", [
    ({"feishu": {"cli": "/x", "chats": ["bad"]}}, "oc_"),
    ({"feishu": {"cli": "/x", "chats": [], "allowed": ["ou_1"]}}, "at least one chat"),
    ({"feishu": {"cli": "/x", "chats": ["oc_1"], "allowed": ["u1"]}}, "ou_"),
    ({"github": {"cli": "/x", "repository": "nope"}}, "owner/name"),
    ({"maxWorkers": 0}, "positive"),
    ({"allowedTools": "Read"}, "list"),
])
def test_config_rejects(tmp_path: Path, extra: dict, error: str) -> None:
    with pytest.raises(ConfigError, match=error):
        load_config(config_file(tmp_path, **extra))


@pytest.mark.unit
def test_config_requires_git_checkout(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"checkout": str(tmp_path)}), encoding="utf-8")
    with pytest.raises(ConfigError, match="git repository"):
        load_config(path)


# ---------- rule merging ----------

@pytest.mark.integration
def test_merged_rules_keep_base_and_add_new(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    (repo / ".yeeharness").mkdir(parents=True)
    rules = repo / ".yeeharness" / "gate-rules.json"
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q", "-b", "main")
    rules.write_text(json.dumps({"rules": [{"id": "R-001", "pattern": "strict"}]}), encoding="utf-8")
    run("git", "add", ".")
    run("git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "base")
    rules.write_text(json.dumps({"rules": [{"id": "R-001", "pattern": "loose"}, {"id": "R-002", "pattern": "new"}]}),
                     encoding="utf-8")
    merged = json.loads(merged_rules(repo, "main", tmp_path / "m.json").read_text(encoding="utf-8"))["rules"]
    assert {r["id"]: r["pattern"] for r in merged} == {"R-001": "strict", "R-002": "new"}
