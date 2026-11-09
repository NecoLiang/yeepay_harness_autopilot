"""Tests for the pure parts of apply_settings: config validation and merges."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import apply_settings as apply


def write_config(tmp_path: Path, **overrides: object) -> Path:
    cli = tmp_path / "cli"
    cli.write_text("", encoding="utf-8")
    data = {"repository": "agent/payment-demo", "githubCli": str(cli), "feishuCli": str(cli),
            "chats": [{"chatId": "oc_1", "name": "演示群"}], "checkout": str(tmp_path)}
    data.update(overrides)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.unit
def test_load_config_defaults(tmp_path: Path) -> None:
    config = apply.load_config(write_config(tmp_path))
    assert config.port == 3082
    assert config.sync_chat == "oc_1"
    assert config.chats[0].listen == "mentions"


@pytest.mark.unit
@pytest.mark.parametrize("overrides, message", [
    ({"repository": "no-slash"}, "owner/name"),
    ({"chats": [{"chatId": "bad", "name": "x"}]}, "chats"),
    ({"chats": [{"chatId": "oc_1", "name": "x", "listen": "loud"}]}, "chats"),
    ({"feishuAllowed": [{"id": "u_1"}]}, "ou_"),
    ({"checkout": "/definitely/missing"}, "does not exist"),
    ({"githubCli": ""}, "non-empty"),
])
def test_load_config_rejects_bad_input(tmp_path: Path, overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        apply.load_config(write_config(tmp_path, **overrides))


@pytest.mark.unit
def test_merge_section_is_idempotent() -> None:
    once = apply.merge_section("default text", "addendum v1")
    twice = apply.merge_section(once, "addendum v2")
    assert twice.count(apply.MARKER) == 1
    assert twice.startswith("default text") and "addendum v2" in twice and "v1" not in twice


@pytest.mark.unit
def test_prompt_config_keeps_other_skills_and_fields() -> None:
    current = {"communication": "c", "scope": "s", "delivery": "d", "skills": {"identities": "x"}, "overrides": {}}
    package = {"sections": {"communication": "C", "scope": "S", "delivery": "D"}, "skills": {"yeeharness": "y"}}
    merged = apply.prompt_config(current, package)
    assert merged["skills"] == {"identities": "x", "yeeharness": "y"}
    assert merged["overrides"] == {}
    assert current["skills"] == {"identities": "x"}


@pytest.mark.unit
def test_policy_value_opens_feishu_and_closes_github(tmp_path: Path) -> None:
    config = apply.load_config(write_config(tmp_path))
    current = {"rules": [{"id": "r"}], "sources": {"github": {"allowed": [{"id": "me"}], "bots": []}}}
    value = apply.policy_value(current, config)
    assert value["sources"]["github"] == {"allowed": [], "bots": []}
    assert value["sources"]["feishu"]["syncChat"] == "oc_1"
    assert value["rules"] == [{"id": "r"}]
    assert current["sources"]["github"]["allowed"] == [{"id": "me"}]


@pytest.mark.unit
def test_revision_lookup() -> None:
    settings = {"blocks": {"policy": {"revision": 4}}, "sources": [{"id": "feishu", "revision": 2}]}
    assert apply._revision(settings, "policy") == 4
    assert apply._revision(settings, "source:feishu") == 2
    assert apply._revision(settings, "source:github") == 0


@pytest.mark.unit
def test_prepare_command_uses_ticket_variables() -> None:
    command = apply.prepare_command("/src/demo")
    assert "git -C /src/demo worktree add" in command and "$DSH_SUPERAGENT_DIR" in command
    assert "+refs/heads/main:refs/remotes/origin/main" in command
    assert "git -C '/my src/demo;rm' fetch" in apply.prepare_command("/my src/demo;rm")


# ---------- end to end against a fake Management API ----------

import socketserver  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.revisions = {"policy": 1, "executor": 1, "source:github": 0, "source:feishu": 0}
        self.prompts = {"revision": 3, "config": {"communication": "c", "scope": "s", "delivery": "d", "skills": {}}}
        self.refuse: str | None = None

    def settings(self) -> dict[str, object]:
        return {"blocks": {"policy": {"value": {"rules": [], "sources": {}}, "revision": self.revisions["policy"]},
                           "executor": {"value": {"maxWorkers": 1, "directory": ""}, "revision": self.revisions["executor"]}},
                "sources": [{"id": k.split(":")[1], "revision": v} for k, v in self.revisions.items() if k.startswith("source:")]}

    def handle(self, method: str, path: str, body: object) -> tuple[int, object]:
        self.calls.append((method, path, body))
        if path == self.refuse:
            return 400, {"error": "refused"}
        if (method, path) == ("GET", "state"):
            return 200, {}
        if (method, path) == ("GET", "settings"):
            return 200, self.settings()
        if (method, path) == ("GET", "prompts"):
            return 200, {"current": self.prompts}
        if (method, path) == ("PUT", "prompts"):
            assert body["baseRevision"] == self.prompts["revision"]
            return 200, {"revision": 4}
        if method == "PUT" and path.startswith("settings/"):
            block = path.split("/", 1)[1]
            assert body["revision"] == self.revisions[block], f"stale revision for {block}"
            self.revisions[block] += 1
            return 200, {"saved": True, "revision": self.revisions[block], "restarting": block == "source:github"}
        if method == "POST" and path.startswith("policy-sync/"):
            return 200, {"policy": {}}
        return 404, {"error": "not found"}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):
    state = FakeApi()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            assert self.headers["x-orchestrator-request"] == "1"
            status, payload = state.handle(self.command, self.path.split("/orchestrator/api/", 1)[1], body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_PUT = do_POST = _serve

        def log_message(self, *args: object) -> None:
            pass

    class QuickServer(ThreadingHTTPServer):
        def server_bind(self) -> None:  # skip the reverse DNS lookup HTTPServer does, slow on macOS
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address[:2]

    server = QuickServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(apply, "POLL_SECONDS", 0)
    yield state, server.server_address[1]
    server.shutdown()


PACKAGE = {"sections": {"communication": "C", "scope": "S", "delivery": "D"}, "skills": {"yeeharness": "y"}}


@pytest.mark.integration
def test_apply_saves_blocks_in_order_with_fresh_revisions(fake, tmp_path: Path) -> None:
    state, port = fake
    config = apply.load_config(write_config(tmp_path, port=port))
    apply.apply(apply.Api(port), config, PACKAGE)
    writes = [(m, p) for m, p, _ in state.calls if m != "GET"]
    assert writes == [("PUT", "settings/source:github"), ("PUT", "settings/source:feishu"), ("PUT", "settings/policy"),
                      ("POST", "policy-sync/feishu"), ("PUT", "settings/executor"), ("PUT", "prompts")]
    feishu = next(b for m, p, b in state.calls if p == "settings/source:feishu")
    assert feishu["value"]["config"]["chats"] == [{"chatId": "oc_1", "name": "演示群", "listen": "mentions"}]
    prompts = next(b for m, p, b in state.calls if p == "prompts" and m == "PUT")
    assert prompts["config"]["skills"] == {"yeeharness": "y"}


@pytest.mark.integration
def test_refused_save_surfaces_api_error(fake, tmp_path: Path) -> None:
    state, port = fake
    state.refuse = "settings/source:feishu"
    code = apply.main(["--config", str(write_config(tmp_path, port=port)), "--package", str(_package(tmp_path))])
    assert code == 1


@pytest.mark.integration
def test_prompts_only(fake, tmp_path: Path) -> None:
    state, port = fake
    config = tmp_path / "port.json"
    config.write_text(json.dumps({"port": port}), encoding="utf-8")
    assert apply.main(["--prompts-only", "--config", str(config), "--package", str(_package(tmp_path))]) == 0
    assert [(m, p) for m, p, _ in state.calls] == [("GET", "prompts"), ("PUT", "prompts")]


def _package(tmp_path: Path) -> Path:
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(PACKAGE), encoding="utf-8")
    return path


@pytest.mark.integration
def test_unreachable_api(tmp_path: Path) -> None:
    with pytest.raises(apply.ApiError, match="unreachable"):
        apply.Api(1).call("GET", "state")
