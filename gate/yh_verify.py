#!/usr/bin/env python3
"""yeeHarness delivery gate.

Checks the lines a change adds against the yeeHarness payment rules (P-xxx), the engineering
rules (G-xxx) and the business rules a repository declares in ``.yeeharness/gate-rules.json``
(R-xxx), then runs the repository's tests. A change may be reported ready only when the verdict
is ``pass``.

Exit codes: 0 pass, 1 blocked, 2 usage or environment error.
Standard library only, so it runs unchanged in an Executor Session, in CI and on a laptop.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

CODE_SUFFIXES = (".java", ".kt", ".scala", ".ts", ".tsx", ".js", ".py", ".go")
TEST_PATH = re.compile(r"(^|/)(src/test/|tests?/)|(Test|Tests|_test|\.spec|\.test)\.[a-z]+$")
BUSINESS_RULES_FILE = ".yeeharness/gate-rules.json"
TEST_OUTPUT_TAIL = 40
TEST_TIMEOUT_SECONDS = 900
SEVERITIES = ("block", "warn")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str
    title: str
    pattern: str
    unless: str = ""
    main_code_only: bool = True
    whole_line_unless: bool = True

    def matches(self, line: str) -> bool:
        """True when some match of the pattern is not itself excused by ``unless``."""
        if self.whole_line_unless:
            return bool(re.search(self.pattern, line)) and not (self.unless and re.search(self.unless, line))
        return any(not (self.unless and re.search(self.unless, m.group(0))) for m in re.finditer(self.pattern, line))


@dataclass(frozen=True)
class AddedLine:
    path: str
    number: int
    text: str


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    title: str
    path: str
    line: int
    code: str


@dataclass(frozen=True)
class TestRun:
    command: str
    exit_code: int
    passed: bool
    output_tail: str


@dataclass(frozen=True)
class Report:
    verdict: str
    base: str
    head: str
    files_changed: tuple[str, ...]
    findings: tuple[Finding, ...]
    tests: TestRun | None
    rules_checked: tuple[str, ...]
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))



BUILTIN_RULES: tuple[Rule, ...] = (
    Rule("P-001", "block", "金额禁止使用 double/float 计算", r"\.(double|float)Value\(\)"),
    Rule("P-001", "block", "金额禁止使用 double/float 计算",
         r"\b(double|float|Double|Float)\b\s+\w*" + r"(?i:amount|amt|money|price|fee|total|share|balance|cents|yuan)"),
    Rule("P-001", "block", "BigDecimal 必须用字符串构造", r"new\s+BigDecimal\(\s*-?\d+\.\d+\s*\)"),
    Rule("P-001", "block", "setScale 必须显式指定舍入模式", r"\.setScale\(\s*[^,()]+\s*\)"),
    Rule("P-001", "block", "金额比较必须用 compareTo",
         r"(?i)\b\w*(amount|money|price|fee|total|share)\w*(\(\))?\.equals\("
         r"|Objects\.equals\(\s*\w*(?i:amount|money|price|fee|total|share)",
         unless=r"(No|Id|ID|Name|Code|Status|Type|Currency|Unit|Flag)(\(\))?\.equals\($", whole_line_unless=False),
    Rule("P-002", "block", "金额空值禁止兜底为 0",
         r"(==\s*null\s*\?\s*BigDecimal\.ZERO)|(!=\s*null\s*\?\s*\w+\s*:\s*BigDecimal\.ZERO)|(orElse\(\s*BigDecimal\.ZERO\s*\))|(getOrDefault\([^)]*BigDecimal\.ZERO)"),
    Rule("P-007", "block", "日志输出敏感字段必须脱敏",
         r"(?i)(log(ger)?\.(info|debug|warn|error|trace)|System\.out\.print).*(?<![A-Za-z])(?:\w*?)(?i:card_?no|bank_?card|id_?card|id_?no|mobile|phone|cvv|password)(?![a-z])",
         unless=r"(?i)mask"),
    Rule("G-003", "block", "骨架/TODO 必须三态归类后才能交付",
         r"UnsupportedOperationException|NotSupportedException|\bTODO\b|\bFIXME\b|尚在开发",
         unless=r"\[骨架:(依赖|不支持)\]", main_code_only=False),
)


class GateError(Exception):
    """A usage or environment problem: the gate could not reach a verdict."""


def git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except FileNotFoundError as error:
        raise GateError("git is not installed") from error
    if result.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve_base(repo: Path, requested: str | None) -> str:
    if requested:
        return git(repo, "rev-parse", "--verify", requested).strip()
    for candidate in ("origin/main", "origin/master", "main", "master"):
        try:
            return git(repo, "merge-base", "HEAD", candidate).strip()
        except GateError:
            continue
    raise GateError("cannot find a base branch; pass --base")


def is_code(path: str) -> bool:
    return path.endswith(CODE_SUFFIXES)


def is_test(path: str) -> bool:
    return bool(TEST_PATH.search(path))


def diff_path(header: str) -> str:
    """The new-side path of a ``+++`` header: unquotes C-style quoting and drops git's trailing TAB."""
    target = header[4:].removesuffix("\t")
    if len(target) > 1 and target.startswith('"') and target.endswith('"'):
        raw = target[1:-1].encode("utf-8").decode("unicode_escape").encode("latin-1")
        target = raw.decode("utf-8", errors="replace")
    return target[2:] if target.startswith("b/") else ""


def parse_added_lines(diff_text: str) -> list[AddedLine]:
    """Turns ``git diff -U0`` output into the added lines with their new line numbers.

    Hunk headers say how many old and new lines follow, so a body line such as ``++ i;`` (shown
    as ``+++ i;``) is never mistaken for a file header.
    """
    added: list[AddedLine] = []
    path, number, old_left, new_left = "", 0, 0, 0
    for raw in diff_text.split("\n"):
        if old_left > 0 or new_left > 0:
            if raw.startswith("+"):
                if path:
                    added.append(AddedLine(path, number, raw[1:]))
                number, new_left = number + 1, new_left - 1
            elif raw.startswith("-"):
                old_left -= 1
            elif raw.startswith(" "):
                number, old_left, new_left = number + 1, old_left - 1, new_left - 1
            continue
        if raw.startswith("+++ "):
            path = diff_path(raw)
        elif raw.startswith("@@"):
            match = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", raw)
            if match:
                old_left = int(match.group(1) or 1)
                number = int(match.group(2))
                new_left = int(match.group(3) or 1)
    return added


def untracked_lines(repo: Path) -> list[AddedLine]:
    lines: list[AddedLine] = []
    for path in filter(None, git(repo, "ls-files", "-z", "--others", "--exclude-standard").split("\0")):
        file = repo / path
        if not is_code(path) or not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        lines.extend(AddedLine(path, i, t) for i, t in enumerate(text.splitlines(), start=1))
    return lines


def load_business_rules(repo: Path, override: Path | None = None) -> tuple[Rule, ...]:
    """Reads and validates the R-xxx rules; a malformed file is an error, never skipped.

    ``override`` replaces the repository's file, so CI can enforce the base branch's rules on a PR.
    """
    file = override or repo / BUSINESS_RULES_FILE
    if not file.is_file():
        return ()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise GateError(f"{BUSINESS_RULES_FILE} is not valid JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise GateError(f"{BUSINESS_RULES_FILE} must be an object with a 'rules' list")
    return tuple(_business_rule(item, index) for index, item in enumerate(data["rules"]))


def _business_rule(item: object, index: int) -> Rule:
    where = f"{BUSINESS_RULES_FILE} rules[{index}]"
    if not isinstance(item, dict):
        raise GateError(f"{where} must be an object")
    for key in ("id", "severity", "title", "pattern"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise GateError(f"{where}.{key} must be a non-empty string")
    if item["severity"] not in SEVERITIES:
        raise GateError(f"{where}.severity must be one of {SEVERITIES}")
    if not isinstance(item.get("unless", ""), str):
        raise GateError(f"{where}.unless must be a string")
    if not isinstance(item.get("main_code_only", True), bool):
        raise GateError(f"{where}.main_code_only must be true or false")
    for key in ("pattern", "unless"):
        try:
            re.compile(item.get(key, ""))
        except re.error as error:
            raise GateError(f"{where}.{key} is not a valid regular expression: {error}") from error
    return Rule(item["id"], item["severity"], item["title"], item["pattern"], item.get("unless", ""),
                bool(item.get("main_code_only", True)))


def scan(lines: Iterable[AddedLine], rules: Sequence[Rule]) -> list[Finding]:
    findings: list[Finding] = []
    for line in lines:
        if not is_code(line.path):
            continue
        for rule in rules:
            if rule.main_code_only and is_test(line.path):
                continue
            if rule.matches(line.text):
                findings.append(Finding(rule.rule_id, rule.severity, rule.title, line.path, line.number,
                                        line.text.strip()[:160]))
    return findings


BIGDECIMAL_DECL = re.compile(r"\bBigDecimal\s+(\w+)\s*[,;=)(]")
EQUALS_TITLE = "金额比较必须用 compareTo"


def bigdecimal_names(source: str) -> frozenset[str]:
    """Names declared as BigDecimal in a file: fields, locals, parameters and record components."""
    return frozenset(BIGDECIMAL_DECL.findall(source))


def equals_findings(lines: Iterable[AddedLine], names_by_path: dict[str, frozenset[str]]) -> list[Finding]:
    """P-001: ``x.equals(...)`` where x is declared BigDecimal in the same file, whatever its name."""
    findings: list[Finding] = []
    for line in lines:
        names = names_by_path.get(line.path, frozenset())
        if not names or is_test(line.path):
            continue
        pattern = r"\b(" + "|".join(map(re.escape, sorted(names))) + r")(\(\))?\.equals\("
        if re.search(pattern, line.text):
            findings.append(Finding("P-001", "block", EQUALS_TITLE, line.path, line.number, line.text.strip()[:160]))
    return findings


def read_sources(repo: Path, paths: Iterable[str]) -> dict[str, frozenset[str]]:
    names: dict[str, frozenset[str]] = {}
    for path in paths:
        file = repo / path
        if is_code(path) and file.is_file():
            names[path] = bigdecimal_names(file.read_text(encoding="utf-8", errors="replace"))
    return names


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, int, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.rule_id, finding.path, finding.line, finding.title)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def missing_test_finding(files: Sequence[str]) -> list[Finding]:
    main = [f for f in files if is_code(f) and not is_test(f)]
    if main and not any(is_test(f) for f in files):
        return [Finding("G-011", "warn", "改动了生产代码但没有新增或修改测试", main[0], 0, "")]
    return []


def default_test_command(repo: Path) -> str | None:
    if (repo / "pom.xml").is_file():
        return "mvn -B -q test"
    if (repo / "package.json").is_file():
        return "npm test --silent"
    if (repo / "pyproject.toml").is_file() or (repo / "pytest.ini").is_file():
        return "python3 -m pytest -q"
    if (repo / "go.mod").is_file():
        return "go test ./..."
    return None


def run_tests(repo: Path, command: str) -> TestRun:
    try:
        result = subprocess.run(command, shell=True, cwd=repo, capture_output=True, text=True,
                                timeout=TEST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return TestRun(command, 124, False, f"timed out after {TEST_TIMEOUT_SECONDS}s")
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-TEST_OUTPUT_TAIL:])
    return TestRun(command, result.returncode, result.returncode == 0, tail)


def evaluate(repo: Path, base_ref: str | None, test_command: str | None, skip_tests: bool,
             rules_file: Path | None = None) -> Report:
    base = resolve_base(repo, base_ref)
    head = git(repo, "rev-parse", "HEAD").strip()
    added = parse_added_lines(git(repo, "-c", "core.quotePath=false", "diff", base, "-U0", "--no-color",
                                  "--no-ext-diff", "--no-renames"))
    added += untracked_lines(repo)
    files = tuple(sorted({line.path for line in added} | set(filter(None, git(repo, "diff", base, "--name-only", "-z", "--no-renames").split("\0")))))
    rules = BUILTIN_RULES + load_business_rules(repo, rules_file)
    typed = equals_findings(added, read_sources(repo, files))
    findings = dedupe(scan(added, rules) + typed) + missing_test_finding(files)
    command = test_command or default_test_command(repo)
    tests = None if skip_tests or not command else run_tests(repo, command)
    blocked = any(f.severity == "block" for f in findings) or (tests is not None and not tests.passed)
    return Report("block" if blocked else "pass", base, head, files, tuple(findings), tests,
                  tuple(sorted({r.rule_id for r in rules})))


def render_markdown(report: Report) -> str:
    icon = "✅ 通过" if report.verdict == "pass" else "⛔ 拦截"
    out = [f"### yeeHarness 交付门禁：{icon}", "",
           f"- 基线 `{report.base[:10]}` → 提交 `{report.head[:10]}`，改动文件 {len(report.files_changed)} 个",
           f"- 已检查规则：{', '.join(report.rules_checked)}"]
    if report.tests is None:
        out.append("- 测试：未运行")
    else:
        out.append(f"- 测试：`{report.tests.command}` → {'通过' if report.tests.passed else '失败'}"
                   f"（exit {report.tests.exit_code}）")
    if report.findings:
        out += ["", "| 规则 | 级别 | 问题 | 位置 |", "|---|---|---|---|"]
        out += [f"| {f.rule_id} | {'拦截' if f.severity == 'block' else '提醒'} | {f.title} | `{f.path}:{f.line}` |"
                for f in report.findings]
    else:
        out += ["", "未发现违反规约的新增代码。"]
    return "\n".join(out) + "\n"


def to_json(report: Report) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="yeeHarness delivery gate")
    parser.add_argument("--repo", default=".", help="repository to check (default: current directory)")
    parser.add_argument("--base", help="base revision (default: merge-base with origin/main)")
    parser.add_argument("--test-cmd", help="test command (default: detected from the build file)")
    parser.add_argument("--no-tests", action="store_true", help="only run the static rules")
    parser.add_argument("--rules", help=f"business rules file to use instead of {BUSINESS_RULES_FILE}")
    parser.add_argument("--json", dest="json_out", help="also write the report as JSON to this file")
    parser.add_argument("--markdown", dest="md_out", help="also write the report as Markdown to this file")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        report = evaluate(repo, args.base, args.test_cmd, args.no_tests, Path(args.rules) if args.rules else None)
    except GateError as error:
        print(f"[yeeHarness gate] {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 — any other failure means "no verdict", never "blocked"
        print(f"[yeeHarness gate] internal error, no verdict: {error!r}", file=sys.stderr)
        return 2
    markdown = render_markdown(report)
    if args.json_out:
        Path(args.json_out).write_text(to_json(report), encoding="utf-8")
    if args.md_out:
        Path(args.md_out).write_text(markdown, encoding="utf-8")
    print(markdown)
    if report.tests is not None and not report.tests.passed:
        print(report.tests.output_tail, file=sys.stderr)
    return 0 if report.verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
