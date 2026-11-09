"""Tests for packaging yeeHarness skills as dsh-superagent team skills."""
from __future__ import annotations

from pathlib import Path

import pytest

import build_skills as build

YEEHARNESS = Path.home() / "yeeharness" / "skills"


def make_repo(root: Path) -> Path:
    skills = root / "skills"
    shared = skills / "yeeHarness-shared"
    shared.mkdir(parents=True)
    for name in ("rules", "payment-domain", "review-loop", "troubleshoot-methodology", "planning-quality",
                 "evolution-capture", "worktree-mode"):
        (shared / f"{name}.md").write_text(f"# {name}\n\n## Part\n{name} body\n", encoding="utf-8")
    for scene in build.SCENES:
        folder = skills / f"yeeHarness-{scene}"
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            f"---\nname: yeeHarness-{scene}\ndescription: >-\n  {scene} 工作流。更多说明\n  第二行\n---\n\n"
            "# Title\n\n参照 `.claude/skills/yeeHarness-shared/review-loop.md` 和 "
            "`.claude/skills/yeeHarness-shared/worktree-mode.md`\n", encoding="utf-8")
    return skills


@pytest.mark.unit
def test_front_matter_folds_multiline_description() -> None:
    meta, body = build.split_front_matter("---\nname: x\ndescription: >-\n  a\n  b\n---\n\nbody\n")
    assert meta == {"name": "x", "description": "a b"}
    assert body == "body\n"


@pytest.mark.unit
def test_front_matter_is_required() -> None:
    with pytest.raises(build.BuildError):
        build.split_front_matter("no front matter")


@pytest.mark.unit
def test_demote_and_strip_title() -> None:
    assert build.demote(build.strip_title("# T\n\n## A\ntext"), 2) == "#### A\ntext"


@pytest.mark.unit
def test_refs_are_rewritten_and_appendices_only_for_non_inlined(tmp_path: Path) -> None:
    package = build.build(make_repo(tmp_path), Path("/gate.py"))
    bugfix = package.skills["yeeharness-bugfix"]
    assert ".claude/skills" not in bugfix
    assert "## 附录「review-loop」" in bugfix
    assert "附录「worktree-mode」" not in bugfix
    assert bugfix.startswith("yeeHarness 场景技能（无人值守）：bugfix 工作流。")
    assert "无人值守适配" in bugfix


@pytest.mark.unit
def test_router_fills_every_placeholder(tmp_path: Path) -> None:
    router = build.build(make_repo(tmp_path), Path("/opt/gate.py")).skills["yeeharness"]
    assert "{{" not in router
    assert "/opt/gate.py" in router
    assert "rules body" in router and "payment-domain body" in router


@pytest.mark.unit
def test_description_limit() -> None:
    with pytest.raises(build.BuildError, match="longer than"):
        build.description("x" * (build.DESCRIPTION_MAX + 1))


@pytest.mark.unit
def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(build.BuildError, match="missing file"):
        build.build(tmp_path / "nope", Path("/gate.py"))


@pytest.mark.integration
@pytest.mark.skipif(not YEEHARNESS.is_dir(), reason="needs the real yeeHarness checkout")
def test_real_yeeharness_builds_within_prompt_budget(tmp_path: Path) -> None:
    out = tmp_path / "prompts.json"
    assert build.main(["--yeeharness", str(YEEHARNESS.parent), "--out", str(out)]) == 0
    assert len(out.read_text(encoding="utf-8")) < 100_000
