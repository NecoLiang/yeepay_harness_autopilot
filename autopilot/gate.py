"""Runs the yeeHarness delivery gate on a worktree.

Business rules are the union of the base branch's rules and the worktree's: a change can add a rule
(evolution) but never remove or weaken one that is already in force.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .models import GateResult

RULES = ".yeeharness/gate-rules.json"
GATE_TIMEOUT_S = 1200


def _rules(text: str) -> list[dict[str, object]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    rules = data.get("rules") if isinstance(data, dict) else None
    return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []


def merged_rules(worktree: Path, base_ref: str, out: Path) -> Path:
    base = subprocess.run(["git", "show", f"{base_ref}:{RULES}"], cwd=worktree, capture_output=True, text=True)
    local = worktree / RULES
    merged: dict[str, dict[str, object]] = {}
    for rule in _rules(local.read_text(encoding="utf-8") if local.is_file() else "{}"):
        merged[str(rule.get("id"))] = rule
    for rule in _rules(base.stdout if base.returncode == 0 else "{}"):
        merged[str(rule.get("id"))] = rule  # the base wins: a change cannot loosen a rule in force
    out.write_text(json.dumps({"rules": list(merged.values())}, ensure_ascii=False), encoding="utf-8")
    return out


def run_gate(gate: Path, worktree: Path, base_ref: str, scratch: Path, test_cmd: str = "") -> GateResult:
    scratch.mkdir(parents=True, exist_ok=True)
    rules = merged_rules(worktree, base_ref, scratch / "rules.json")
    md, js = scratch / "gate.md", scratch / "gate.json"
    for file in (md, js):
        file.unlink(missing_ok=True)
    try:
        result = subprocess.run([sys.executable, str(gate), "--repo", str(worktree), "--base", base_ref,
                                 "--rules", str(rules), "--markdown", str(md), "--json", str(js),
                                 *(["--test-cmd", test_cmd] if test_cmd else [])],
                                capture_output=True, text=True, timeout=GATE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return GateResult("error", f"门禁超时（{GATE_TIMEOUT_S}s）")
    if result.returncode not in (0, 1) or not md.is_file():
        return GateResult("error", f"门禁无法运行：{result.stderr.strip()[-800:]}")
    findings = tuple(sorted({f["rule_id"] for f in json.loads(js.read_text(encoding="utf-8"))["findings"]
                             if f["severity"] == "block"}))
    return GateResult("pass" if result.returncode == 0 else "block", md.read_text(encoding="utf-8"), findings)
