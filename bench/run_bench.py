#!/usr/bin/env python3
"""Runs the delivery-gate benchmark against a throwaway clone of demo/payment-demo.

Writes ``bench/results.json`` and ``bench/results.md``: per-case verdicts, the block rate on
mistakes, the false-block rate on correct changes, and per-rule coverage.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import CASES, Case  # noqa: E402

DEMO = ROOT / "demo" / "payment-demo"
GATE = ROOT / "gate" / "yh_verify.py"
GIT_ID = ["-c", "user.name=bench", "-c", "user.email=bench@example.com"]


@dataclass(frozen=True)
class Outcome:
    name: str
    rule: str
    expect: str
    verdict: str
    correct: bool
    findings: tuple[str, ...]
    tests: str
    seconds: float
    note: str


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def checked(cwd: Path, *args: str) -> None:
    result = run(cwd, *args)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")


def apply_case(repo: Path, case: Case) -> None:
    checked(repo, "git", "checkout", "-q", "main")
    checked(repo, "git", "checkout", "-q", "-B", "case")
    for path, text in case.files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if case.business_rules:
        rules = repo / ".yeeharness" / "gate-rules.json"
        rules.write_text(json.dumps({"rules": list(case.business_rules)}, ensure_ascii=False), encoding="utf-8")
    checked(repo, "git", "add", "-A")
    checked(repo, "git", *GIT_ID, "commit", "-q", "-m", case.name)


def evaluate(repo: Path, case: Case, report: Path) -> Outcome:
    apply_case(repo, case)
    report.unlink(missing_ok=True)
    args = [sys.executable, str(GATE), "--repo", str(repo), "--base", "main", "--json", str(report)]
    if not case.run_tests:
        args.append("--no-tests")
    started = time.monotonic()
    result = run(repo, *args)
    elapsed = round(time.monotonic() - started, 2)
    if result.returncode not in (0, 1) or not report.is_file():
        raise RuntimeError(f"gate could not run for {case.name}: {result.stderr.strip()}")
    data = json.loads(report.read_text(encoding="utf-8"))
    blocking = tuple(sorted({f["rule_id"] for f in data["findings"] if f["severity"] == "block"}))
    tests = "未运行" if data["tests"] is None else ("通过" if data["tests"]["passed"] else "失败")
    return Outcome(case.name, case.rule, case.expect, data["verdict"], data["verdict"] == case.expect,
                   blocking, tests, elapsed, case.note)


def summarize(outcomes: list[Outcome]) -> dict[str, object]:
    bad = [o for o in outcomes if o.expect == "block"]
    good = [o for o in outcomes if o.expect == "pass"]
    rules: dict[str, dict[str, int]] = {}
    for o in outcomes:
        entry = rules.setdefault(o.rule, {"cases": 0, "correct": 0})
        entry["cases"] += 1
        entry["correct"] += int(o.correct)
    return {
        "cases": len(outcomes),
        "accuracy": round(sum(o.correct for o in outcomes) / len(outcomes), 4),
        "block_rate_on_mistakes": round(sum(o.verdict == "block" for o in bad) / len(bad), 4),
        "false_block_rate_on_correct": round(sum(o.verdict == "block" for o in good) / len(good), 4),
        "per_rule": rules,
    }


def markdown(summary: dict[str, object], outcomes: list[Outcome]) -> str:
    lines = ["# 交付门禁基准测试结果", "",
             f"- 用例 {summary['cases']} 个，判定正确率 **{summary['accuracy']:.0%}**",
             f"- 错误写法拦截率 **{summary['block_rate_on_mistakes']:.0%}**，"
             f"正确改动误拦率 **{summary['false_block_rate_on_correct']:.0%}**", "",
             "| 用例 | 规则 | 期望 | 实际 | 命中规则 | 测试 | 耗时(s) | 结果 |", "|---|---|---|---|---|---|---|---|"]
    for o in outcomes:
        lines.append(f"| {o.name} | {o.rule} | {o.expect} | {o.verdict} | {', '.join(o.findings) or '—'} | "
                     f"{o.tests} | {o.seconds} | {'✅' if o.correct else '❌'} |")
    lines += ["", "> 用例由本项目编写，覆盖 yeeHarness 规约针对的典型错误写法与对应的正确写法；",
              "> 它度量门禁规则是否按设计生效，不代表对任意代码库的检出率。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="yh-bench-") as tmp:
        repo = Path(tmp) / "repo"
        checked(ROOT, "bash", str(ROOT / "scripts" / "init_demo_repo.sh"), str(repo))
        report = Path(tmp) / "report.json"
        outcomes = []
        for case in CASES:
            outcome = evaluate(repo, case, report)
            print(f"{'✅' if outcome.correct else '❌'} {outcome.name}: {outcome.verdict} {outcome.findings}")
            outcomes.append(outcome)
    summary = summarize(outcomes)
    out = Path(__file__).resolve().parent
    (out / "results.json").write_text(json.dumps({"summary": summary, "cases": [asdict(o) for o in outcomes]},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "results.md").write_text(markdown(summary, outcomes), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if all(o.correct for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
