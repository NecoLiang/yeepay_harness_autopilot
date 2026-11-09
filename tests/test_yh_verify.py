"""Tests for the yeeHarness delivery gate."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import yh_verify as gate

MAIN = "src/main/java/com/x/Split.java"
TEST = "src/test/java/com/x/SplitTest.java"


def blocked_rules(text: str, path: str = MAIN) -> set[str]:
    findings = gate.scan([gate.AddedLine(path, 1, text)], gate.BUILTIN_RULES)
    return {f.rule_id for f in findings if f.severity == "block"}


@pytest.mark.unit
@pytest.mark.parametrize("line", [
    "double total = orderAmount.doubleValue();",
    "float fee = 0.6f;",
    "BigDecimal a = new BigDecimal(0.1);",
    "return amount.setScale(2);",
    "if (amount().equals(other)) {",
])
def test_p001_blocks_floating_point_money(line: str) -> None:
    assert "P-001" in blocked_rules(line)


@pytest.mark.unit
@pytest.mark.parametrize("line", [
    'BigDecimal a = new BigDecimal("0.1");',
    "return amount.setScale(2, RoundingMode.DOWN);",
    "if (amount.compareTo(other) == 0) {",
    "if (merchantNo().equals(other)) {",
    "double ratioOfSomething = 1;",
])
def test_p001_allows_safe_money_code(line: str) -> None:
    assert "P-001" not in blocked_rules(line)


@pytest.mark.unit
@pytest.mark.parametrize("line", [
    "BigDecimal a = amount == null ? BigDecimal.ZERO : amount;",
    "BigDecimal a = Optional.ofNullable(x).orElse(BigDecimal.ZERO);",
    "fees.getOrDefault(key, BigDecimal.ZERO);",
])
def test_p002_blocks_zero_fallback(line: str) -> None:
    assert "P-002" in blocked_rules(line)


@pytest.mark.unit
def test_p007_blocks_unmasked_sensitive_log_but_allows_masked() -> None:
    assert "P-007" in blocked_rules('log.info("pay card {}", cardNo);')
    assert "P-007" not in blocked_rules('log.info("pay card {}", mask(cardNo));')


@pytest.mark.unit
def test_g003_skeleton_markers_respect_classification() -> None:
    assert "G-003" in blocked_rules("// TODO handle refund")
    assert "G-003" not in blocked_rules("// TODO [骨架:依赖] wait for channel SDK 2.1")


@pytest.mark.unit
def test_money_rules_skip_test_code_but_skeleton_rule_does_not() -> None:
    assert blocked_rules("double total = x.doubleValue();", TEST) == set()
    assert "G-003" in blocked_rules("// FIXME", TEST)


@pytest.mark.unit
def test_non_code_files_are_ignored() -> None:
    assert blocked_rules("double amount = 1;", "README.md") == set()


@pytest.mark.unit
def test_parse_added_lines_tracks_paths_and_numbers() -> None:
    diff = "\n".join([
        "diff --git a/A.java b/A.java", "--- a/A.java", "+++ b/A.java",
        "@@ -3,0 +4,2 @@", "+first", "+second",
        "diff --git a/B.java b/B.java", "--- a/B.java", "+++ /dev/null", "@@ -1 +0,0 @@", "-gone",
    ])
    lines = gate.parse_added_lines(diff)
    assert lines == [gate.AddedLine("A.java", 4, "first"), gate.AddedLine("A.java", 5, "second")]


@pytest.mark.unit
def test_missing_test_warning() -> None:
    assert gate.missing_test_finding([MAIN])[0].rule_id == "G-011"
    assert gate.missing_test_finding([MAIN, TEST]) == []
    assert gate.missing_test_finding(["README.md"]) == []


# ---------- business rules (R-xxx) ----------

def write_rules(repo: Path, payload: object) -> None:
    (repo / ".yeeharness").mkdir(exist_ok=True)
    (repo / gate.BUSINESS_RULES_FILE).write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.unit
def test_business_rules_load_and_match(tmp_path: Path) -> None:
    write_rules(tmp_path, {"rules": [{"id": "R-001", "severity": "block", "title": "分账尾差必须归平台",
                                      "pattern": r"remainder.*first\("}]})
    rules = gate.load_business_rules(tmp_path)
    assert rules[0].rule_id == "R-001"
    assert gate.scan([gate.AddedLine(MAIN, 1, "remainder -> first(shares)")], rules)[0].rule_id == "R-001"


@pytest.mark.unit
def test_missing_business_rules_file_is_fine(tmp_path: Path) -> None:
    assert gate.load_business_rules(tmp_path) == ()


@pytest.mark.unit
@pytest.mark.parametrize("payload, message", [
    ([], "must be an object"),
    ({"rules": ["x"]}, "must be an object"),
    ({"rules": [{"id": "R-1", "severity": "fatal", "title": "t", "pattern": "p"}]}, "severity"),
    ({"rules": [{"id": "R-1", "severity": "block", "title": "t", "pattern": "("}]}, "regular expression"),
    ({"rules": [{"id": "", "severity": "block", "title": "t", "pattern": "p"}]}, "id"),
])
def test_invalid_business_rules_fail_loudly(tmp_path: Path, payload: object, message: str) -> None:
    write_rules(tmp_path, payload)
    with pytest.raises(gate.GateError, match=message):
        gate.load_business_rules(tmp_path)


@pytest.mark.unit
def test_broken_json_fails_loudly(tmp_path: Path) -> None:
    (tmp_path / ".yeeharness").mkdir()
    (tmp_path / gate.BUSINESS_RULES_FILE).write_text("{", encoding="utf-8")
    with pytest.raises(gate.GateError, match="not valid JSON"):
        gate.load_business_rules(tmp_path)


# ---------- end to end on a real git repository ----------

def sh(repo: Path, *args: str) -> None:
    subprocess.run(args, cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    sh(tmp_path, "git", "init", "-q", "-b", "main")
    sh(tmp_path, "git", "config", "user.email", "t@example.com")
    sh(tmp_path, "git", "config", "user.name", "t")
    main = tmp_path / MAIN
    main.parent.mkdir(parents=True)
    main.write_text("class Split {}\n", encoding="utf-8")
    sh(tmp_path, "git", "add", ".")
    sh(tmp_path, "git", "commit", "-q", "-m", "init")
    sh(tmp_path, "git", "checkout", "-q", "-b", "agent/fix")
    return tmp_path


def commit(repo: Path, path: str, text: str) -> None:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    sh(repo, "git", "add", ".")
    sh(repo, "git", "commit", "-q", "-m", "change")


@pytest.mark.integration
def test_cli_blocks_bad_change_and_writes_reports(repo: Path, tmp_path: Path) -> None:
    commit(repo, MAIN, "class Split {\n  double total = amount.doubleValue();\n}\n")
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    code = gate.main(["--repo", str(repo), "--test-cmd", "true", "--json", str(out_json), "--markdown", str(out_md)])
    assert code == 1
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["verdict"] == "block"
    assert {f["line"] for f in report["findings"] if f["rule_id"] == "P-001"} == {2}
    assert "⛔ 拦截" in out_md.read_text(encoding="utf-8")


@pytest.mark.integration
def test_cli_passes_clean_change_with_tests(repo: Path) -> None:
    commit(repo, MAIN, 'class Split {\n  BigDecimal t = new BigDecimal("1.00");\n}\n')
    commit(repo, TEST, "class SplitTest {}\n")
    assert gate.main(["--repo", str(repo), "--test-cmd", "true"]) == 0


@pytest.mark.integration
def test_failing_tests_block(repo: Path) -> None:
    commit(repo, TEST, "class SplitTest {}\n")
    assert gate.main(["--repo", str(repo), "--test-cmd", "false"]) == 1


@pytest.mark.integration
def test_untracked_files_are_scanned(repo: Path) -> None:
    (repo / "src/main/java/com/x/New.java").write_text("// TODO later\n", encoding="utf-8")
    assert gate.main(["--repo", str(repo), "--no-tests"]) == 1


@pytest.mark.integration
def test_business_rule_blocks_after_it_is_added(repo: Path) -> None:
    commit(repo, MAIN, "class Split { void f() { remainder.first(); } }\n")
    commit(repo, TEST, "class SplitTest {}\n")
    assert gate.main(["--repo", str(repo), "--no-tests"]) == 0
    write_rules(repo, {"rules": [{"id": "R-001", "severity": "block", "title": "尾差归属", "pattern": r"remainder\.first"}]})
    assert gate.main(["--repo", str(repo), "--no-tests"]) == 1


@pytest.mark.integration
def test_usage_error_exit_code(tmp_path: Path) -> None:
    assert gate.main(["--repo", str(tmp_path), "--no-tests"]) == 2


@pytest.mark.unit
def test_bigdecimal_names_cover_fields_params_and_records() -> None:
    src = "record A(String no, BigDecimal paid) {}\nvoid f(BigDecimal refunded, int x) { BigDecimal fee = y; }"
    assert gate.bigdecimal_names(src) == {"paid", "refunded", "fee"}


@pytest.mark.unit
def test_typed_equals_blocks_any_bigdecimal_name() -> None:
    lines = [gate.AddedLine(MAIN, 3, "if (paid.equals(refunded)) {"), gate.AddedLine(MAIN, 4, "if (no.equals(x)) {")]
    findings = gate.equals_findings(lines, {MAIN: frozenset({"paid"})})
    assert [(f.rule_id, f.line) for f in findings] == [("P-001", 3)]
    assert gate.equals_findings(lines, {TEST: frozenset({"paid"})}) == []


@pytest.mark.unit
def test_dedupe_keeps_first_of_identical_findings() -> None:
    f = gate.Finding("P-001", "block", "t", MAIN, 1, "x")
    assert gate.dedupe([f, f]) == [f]


# ---------- regressions found by independent review ----------

@pytest.mark.unit
@pytest.mark.parametrize("line", [
    "if (o.getPaidAmount().equals(x)) {",
    "if (amount.equals(x) && orderNo.equals(y)) {",
    "return Objects.equals(amount, other);",
])
def test_equals_review_regressions_block(line: str) -> None:
    assert "P-001" in blocked_rules(line)


@pytest.mark.unit
@pytest.mark.parametrize("line", ['if (feeCurrency.equals("CNY")) {', "if (totalStatus.equals(s)) {"])
def test_equals_on_non_amount_receivers_passes(line: str) -> None:
    assert "P-001" not in blocked_rules(line)


@pytest.mark.unit
def test_p002_reverse_ternary_and_p007_false_positive() -> None:
    assert "P-002" in blocked_rules("BigDecimal a = amount != null ? amount : BigDecimal.ZERO;")
    assert "P-007" not in blocked_rules('log.info("paidNotify received {}", orderNo);')
    assert "P-007" in blocked_rules('log.info("pay {}", userCardNo);')


@pytest.mark.unit
def test_plus_plus_body_line_is_not_a_file_header() -> None:
    diff = "\n".join(["+++ b/W.java", "@@ -0,0 +1,2 @@", "+++ i;", "+double amount = 1.0;"])
    assert [l.text for l in gate.parse_added_lines(diff)] == ["++ i;", "double amount = 1.0;"]


@pytest.mark.unit
def test_diff_path_handles_tab_and_quoted_unicode() -> None:
    assert gate.diff_path("+++ b/a b/X.java\t") == "a b/X.java"
    assert gate.diff_path('+++ "b/\\346\\224\\257/Y.java"') == "支/Y.java"


@pytest.mark.integration
@pytest.mark.parametrize("path", ["src/main/java/a b/X.java", "src/main/java/支付/Y.java"])
def test_unusual_paths_are_scanned(repo: Path, path: str) -> None:
    commit(repo, path, "class X {\n  double amount = 1.0;\n}\n")
    assert gate.main(["--repo", str(repo), "--no-tests"]) == 1


@pytest.mark.unit
@pytest.mark.parametrize("item, message", [
    ({"id": "R-1", "severity": "block", "title": "t", "pattern": "p", "unless": None}, "unless"),
    ({"id": "R-1", "severity": "block", "title": "t", "pattern": "p", "main_code_only": "false"}, "main_code_only"),
])
def test_business_rule_field_types(tmp_path: Path, item: dict, message: str) -> None:
    write_rules(tmp_path, {"rules": [item]})
    with pytest.raises(gate.GateError, match=message):
        gate.load_business_rules(tmp_path)


@pytest.mark.unit
def test_unexpected_error_means_no_verdict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*args: object) -> None:
        raise RuntimeError("boom")
    monkeypatch.setattr(gate, "evaluate", boom)
    assert gate.main(["--repo", str(tmp_path)]) == 2


@pytest.mark.integration
def test_rules_override_ignores_rules_weakened_in_the_change(repo: Path, tmp_path: Path) -> None:
    strict = tmp_path / "base-rules.json"
    strict.write_text(json.dumps({"rules": [{"id": "R-001", "severity": "block", "title": "t", "pattern": "HALF_UP"}]}),
                      encoding="utf-8")
    commit(repo, MAIN, "class Split { RoundingMode m = RoundingMode.HALF_UP; }\n")
    commit(repo, TEST, "class SplitTest {}\n")
    write_rules(repo, {"rules": []})
    assert gate.main(["--repo", str(repo), "--no-tests"]) == 0
    assert gate.main(["--repo", str(repo), "--no-tests", "--rules", str(strict)]) == 1
