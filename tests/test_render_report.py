"""Tests for the results page."""
from __future__ import annotations

import pytest

import render_report as report

BENCH = {"summary": {"cases": 2, "accuracy": 1.0, "block_rate_on_mistakes": 1.0, "false_block_rate_on_correct": 0.0},
         "cases": [{"name": "<script>x</script>", "rule": "P-001", "expect": "block", "verdict": "block",
                    "findings": ["P-001"], "tests": "未运行", "correct": True}]}
LIVE = {"collected_at": "2026-11-10T10:00:00+08:00",
        "summary": {"tickets": 1, "ready_or_done": 1, "median_minutes_to_ready": 42.0,
                    "agent_messages_per_ticket": 2, "human_messages_per_ticket": 1},
        "tickets": [{"title": "分账差一分", "outcome": "completed", "minutes_to_ready": 42.0,
                     "agent_messages": 2, "human_messages": 1}]}


@pytest.mark.unit
def test_page_escapes_and_shows_numbers() -> None:
    page = report.render(BENCH, LIVE, "https://example.com/repo", "https://example.com/demo")
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page
    assert "100%" in page and "42 分钟" in page and "https://example.com/demo/pulls" in page


@pytest.mark.unit
def test_missing_data_is_stated_not_faked() -> None:
    page = report.render(None, None, "", "")
    assert "尚未运行" in page and "尚无实跑工单" in page


@pytest.mark.integration
def test_main_writes_page(tmp_path) -> None:
    out = tmp_path / "index.html"
    assert report.main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
