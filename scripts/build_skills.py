#!/usr/bin/env python3
"""Builds the dsh-superagent team prompt package from the yeeHarness skill repository.

The yeeHarness skills stay the single source of truth: this script reads them, applies the
unattended adapter and writes ``dist/prompts.json`` with the team-section addenda and the team
skills that ``apply_settings.py`` saves through the dsh-superagent Management API.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEAM = ROOT / "team"
GATE = ROOT / "gate" / "yh_verify.py"
SCENES = ("bugfix", "iterate", "feature")
SHARED_REF = re.compile(r"`?\.claude/skills/yeeHarness-shared/([a-z-]+)\.md`?")
# Covered by the router skill (rules, domain, evolution loop) or replaced by the adapter (worktree).
INLINED_ELSEWHERE = {"rules", "payment-domain", "evolution-capture", "worktree-mode"}
SECTIONS = ("communication", "scope", "delivery")
DESCRIPTION_MAX = 120


@dataclass(frozen=True)
class Package:
    sections: dict[str, str]
    skills: dict[str, str]

    def to_json(self) -> str:
        return json.dumps({"sections": self.sections, "skills": self.skills}, ensure_ascii=False, indent=2)


class BuildError(Exception):
    """The yeeHarness repository does not have the layout this build expects."""


def read(path: Path) -> str:
    if not path.is_file():
        raise BuildError(f"missing file: {path}")
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise BuildError("skill file has no front matter")
    meta: dict[str, str] = {}
    key = ""
    for line in match.group(1).splitlines():
        field = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if field:
            key, value = field.group(1), field.group(2)
            meta[key] = "" if value in (">-", ">", "|") else value
        elif key:
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, text[match.end():].lstrip("\n")


def strip_title(text: str) -> str:
    """Drops a document's H1 so it can be embedded under another heading."""
    return re.sub(r"^# .*\n+", "", text.lstrip(), count=1).strip()


def demote(text: str, levels: int = 1) -> str:
    return re.sub(r"^(#{1,5}) ", lambda m: "#" * (len(m.group(1)) + levels) + " ", text, flags=re.M)


def shared_refs(body: str) -> list[str]:
    seen: list[str] = []
    for name in SHARED_REF.findall(body):
        if name not in seen and name not in INLINED_ELSEWHERE:
            seen.append(name)
    return seen


def rewrite_refs(body: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in INLINED_ELSEWHERE:
            return "`dsh-superagent-yeeharness` 技能（规约 / 进化闭环）或上方「无人值守适配」"
        return f"本技能附录「{name}」"
    return SHARED_REF.sub(replace, body)


def description(text: str) -> str:
    one_line = re.sub(r"\s+", " ", text).strip()
    if len(one_line) > DESCRIPTION_MAX:
        raise BuildError(f"description longer than {DESCRIPTION_MAX} characters: {one_line}")
    return one_line


def scene_skill(source: Path, scene: str, adapter: str) -> str:
    meta, body = split_front_matter(read(source / f"yeeHarness-{scene}" / "SKILL.md"))
    summary = meta.get("description", "").split("。")[0]
    head = description(f"yeeHarness 场景技能（无人值守）：{summary}。由 dsh-superagent-yeeharness 路由后加载。")
    appendix = [f"## 附录「{name}」\n\n{demote(strip_title(read(source / 'yeeHarness-shared' / f'{name}.md')))}"
                for name in shared_refs(body)]
    parts = [head, adapter.strip(), rewrite_refs(body).strip(), *appendix]
    return "\n\n".join(parts) + "\n"


def router_skill(source: Path, gate_path: Path) -> str:
    shared = source / "yeeHarness-shared"
    text = read(TEAM / "router.md")
    text = text.replace("{{RULES}}", demote(strip_title(read(shared / "rules.md")), 2))
    text = text.replace("{{PAYMENT_DOMAIN}}", demote(strip_title(read(shared / "payment-domain.md")), 2))
    text = text.replace("{{GATE_FALLBACK}}", str(gate_path))
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if leftover:
        raise BuildError(f"unfilled placeholders in router.md: {leftover}")
    description(text.split("\n", 1)[0])
    return text


def build(source: Path, gate_path: Path) -> Package:
    adapter = read(TEAM / "adapter.md")
    skills = {"yeeharness": router_skill(source, gate_path)}
    skills.update({f"yeeharness-{scene}": scene_skill(source, scene, adapter) for scene in SCENES})
    sections = {name: read(TEAM / f"{name}.md").strip() + "\n" for name in SECTIONS}
    return Package(sections, skills)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yeeharness", default=os.environ.get("YEEHARNESS_HOME", str(Path.home() / "yeeharness")),
                        help="yeeHarness repository (default: $YEEHARNESS_HOME or ~/yeeharness)")
    parser.add_argument("--gate", default=str(GATE), help="absolute gate path workers fall back to")
    parser.add_argument("--out", default=str(ROOT / "dist" / "prompts.json"))
    args = parser.parse_args(argv)
    try:
        package = build(Path(args.yeeharness) / "skills", Path(args.gate).resolve())
    except BuildError as error:
        print(f"[build_skills] {error}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(package.to_json(), encoding="utf-8")
    sizes = {name: len(text) for name, text in package.skills.items()}
    print(f"wrote {out}: skills {sizes}, total {len(package.to_json())} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
