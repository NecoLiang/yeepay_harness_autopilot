"""The contract between the orchestrator and a Claude run.

Headless Claude cannot ask anyone anything, so it ends every run by writing a report file; the
orchestrator reads it and decides what reaches people. Prompts for each kind of run live here too.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Report, RuleProposal

STATES = ("ready", "question", "blocked")
MAX_MESSAGE = 400
MAX_TITLE = 120


class ReportError(ValueError):
    """The report file is missing or does not follow the contract."""


def _text(data: dict[str, Any], key: str, limit: int, required: bool) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ReportError(f"{key} must be a string")
    value = value.strip()
    if required and not value:
        raise ReportError(f"{key} is required")
    if len(value) > limit:
        raise ReportError(f"{key} is longer than {limit} characters")
    return value


def read_report(path: Path) -> Report:
    if not path.is_file():
        raise ReportError(f"no report file at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReportError(f"report is not valid JSON: {error}") from error
    if not isinstance(data, dict) or data.get("state") not in STATES:
        raise ReportError(f"state must be one of {STATES}")
    state = data["state"]
    proposal = data.get("rule_proposal")
    rule = None
    if proposal:
        if not isinstance(proposal, dict):
            raise ReportError("rule_proposal must be an object")
        rule = RuleProposal(_text(proposal, "id", 20, True), _text(proposal, "title", 80, True))
    return Report(state=state, message=_text(data, "message", MAX_MESSAGE, True),
                  scenario=_text(data, "scenario", 40, False),
                  pr_title=_text(data, "pr_title", MAX_TITLE, state == "ready"),
                  pr_body=_text(data, "pr_body", 60_000, state == "ready"), rule_proposal=rule)


def _contract(report: Path) -> str:
    return (f"\n\n结束本轮前，必须把报告写到 `{report}`（覆盖旧文件，不要提交到 git），格式见系统提示词「报告文件」。")


def first_prompt(request: str, requester: str, report: Path) -> str:
    return (f"飞书群里有人（{requester}）向你提了一个需求，原文如下：\n\n> {request}\n\n"
            "你在一个独立的 git worktree 里，分支已经建好。按系统提示词的 Autopilot 规则处理。" + _contract(report))


def followup_prompt(messages: list[str], report: Path) -> str:
    quoted = "\n".join(f"> {m}" for m in messages)
    return f"需求话题里有人回复了：\n\n{quoted}\n\n据此继续工作（回答你的问题、补充信息或审批规约）。" + _contract(report)


def gate_prompt(gate_markdown: str, report: Path) -> str:
    return ("你报告了 ready，但 yeeHarness 交付门禁没有通过，所以没有交付。门禁报告：\n\n"
            f"{gate_markdown}\n\n逐条修复后提交，再报告 ready；确实无法修复就报告 blocked 并说明原因。" + _contract(report))


def repair_prompt(problem: str, report: Path) -> str:
    return f"上一轮结束时出了问题：{problem}。请处理后重新结束本轮。" + _contract(report)
