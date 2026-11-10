#!/usr/bin/env python3
"""Renders site/index.html, the public results page, from bench/results.json and metrics/metrics.json.

Every number on the page comes from those two files; a section without data says so instead of
showing placeholders. All text is HTML-escaped.
"""
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

STYLE = """
:root { --fg:#1f2328; --muted:#59636e; --line:#d1d9e0; --bg:#ffffff; --soft:#f6f8fa; --ok:#1a7f37; --bad:#cf222e; --accent:#0969da; }
@media (prefers-color-scheme: dark) { :root { --fg:#e6edf3; --muted:#9198a1; --line:#3d444d; --bg:#0d1117; --soft:#151b23; --ok:#3fb950; --bad:#f85149; --accent:#4493f8; } }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.6 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color:var(--fg); background:var(--bg); }
main { max-width: 980px; margin: 0 auto; padding: 40px 20px 80px; }
h1 { font-size: 28px; margin: 0 0 6px; } h2 { font-size: 20px; margin: 40px 0 12px; border-bottom: 1px solid var(--line); padding-bottom: 6px; }
.lead { color: var(--muted); margin: 0 0 24px; }
.flow { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.flow span { background:var(--soft); border:1px solid var(--line); border-radius:6px; padding:6px 10px; }
.flow i { color:var(--muted); font-style:normal; }
.figures { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; }
.figure { border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
.figure b { display:block; font-size:24px; } .figure small { color:var(--muted); }
table { width:100%; border-collapse:collapse; font-size:14px; } th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; } .ok { color:var(--ok); } .bad { color:var(--bad); }
.note { color:var(--muted); font-size:13px; } a { color:var(--accent); }
"""


def load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float) -> str:
    return f"{value:.0%}"


def figure(value: str, label: str) -> str:
    return f'<div class="figure"><b>{escape(value)}</b><small>{escape(label)}</small></div>'


def bench_section(bench: dict[str, Any] | None) -> str:
    if bench is None:
        return "<h2>交付门禁基准</h2><p class=note>尚未运行：<code>python bench/run_bench.py</code></p>"
    s = bench["summary"]
    rows = "".join(
        f"<tr><td>{escape(c['name'])}</td><td>{escape(c['rule'])}</td><td>{escape(c['expect'])}</td>"
        f"<td>{escape(c['verdict'])}</td><td>{escape(', '.join(c['findings']) or '—')}</td><td>{escape(c['tests'])}</td>"
        f"<td class={'ok' if c['correct'] else 'bad'}>{'✓' if c['correct'] else '✗'}</td></tr>" for c in bench["cases"])
    return (
        "<h2>交付门禁基准（可复现）</h2><div class=figures>"
        + figure(str(s["cases"]), "用例数")
        + figure(pct(s["block_rate_on_mistakes"]), "错误写法拦截率")
        + figure(pct(s["false_block_rate_on_correct"]), "正确改动误拦率")
        + figure(pct(s["accuracy"]), "判定正确率")
        + "</div><table><tr><th>用例</th><th>规则</th><th>期望</th><th>实际</th><th>命中</th><th>测试</th><th></th></tr>"
        + rows + "</table><p class=note>用例覆盖 yeeHarness 规约针对的典型错误写法与对应正确写法，"
        "度量规则是否按设计生效，不代表任意代码库的检出率。复现：<code>python bench/run_bench.py</code></p>")


def minutes(value: Any) -> str:
    return "—" if value is None else f"{value:g} 分钟"


def live_section(live: dict[str, Any] | None, repo_url: str) -> str:
    if live is None or not live["summary"]["tickets"]:
        return ("<h2>实跑数据</h2><p class=note>尚无实跑工单。完成实跑后运行 "
                "<code>python scripts/collect_metrics.py && python scripts/render_report.py</code> 自动填充。</p>")
    s = live["summary"]
    rows = "".join(
        f"<tr><td>{escape(t['title'])}</td><td>{escape(t['state'])}</td><td>{escape(minutes(t['minutes_to_ready']))}</td>"
        f"<td>{t['agent_messages']}</td><td>{t['human_messages']}</td><td>{t['gate_blocks']}</td>"
        f"<td>{'$%.2f' % t['cost_usd']}</td>"
        f"<td>{('<a href=\"%s\">PR</a>' % escape(t['pr_url'])) if t['pr_url'] else '—'}</td></tr>" for t in live["tickets"])
    pulls = f'<p>全部 PR：<a href="{escape(repo_url)}/pulls?q=is%3Apr">{escape(repo_url)}/pulls</a></p>' if repo_url else ""
    return (
        f"<h2>实跑数据</h2><p class=note>采集于 {escape(live['collected_at'])}，来源：Autopilot 状态库（只读）</p>"
        "<div class=figures>"
        + figure(str(s["tickets"]), "工单数")
        + figure(f"{s['ready_or_done']}/{s['tickets']}", "已交付 / 总数")
        + figure(minutes(s["median_minutes_to_ready"]), "需求到可评审 PR（中位数）")
        + figure(str(s["agent_messages_per_ticket"]), "每单机器人发言条数")
        + figure(str(s["human_messages_per_ticket"]), "每单人工追加发言")
        + figure(str(s["gate_blocks_total"]), "门禁退回次数（未打扰人）")
        + figure("$%.2f" % (s["cost_usd_per_ticket"] or 0), "每单模型成本")
        + "</div><table><tr><th>工单</th><th>状态</th><th>到可评审</th><th>机器人发言</th><th>人工追加</th>"
          "<th>门禁退回</th><th>成本</th><th></th></tr>"
        + rows + "</table>" + pulls)


def render(bench: dict[str, Any] | None, live: dict[str, Any] | None, repo_url: str, demo_url: str) -> str:
    links = " · ".join(f'<a href="{escape(u)}">{escape(t)}</a>' for t, u in (("代码仓库", repo_url), ("演示仓库", demo_url)) if u)
    flow = "<i>→</i>".join(f"<span>{escape(x)}</span>" for x in (
        "飞书 @机器人", "准入", "Claude Code 无头会话", "yeeHarness 技能", "交付门禁", "GitHub PR", "飞书交付", "进化审批"))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>yeeHarness Autopilot</title><style>{STYLE}</style></head>
<body><main>
<h1>yeeHarness Autopilot</h1>
<p class=lead>团队在飞书群里 @它提需求；它按 yeeHarness 支付研发流程把活干完，PR 过了门禁才交付，并把这次踩的坑变成下一次的门禁。{(' ' + links) if links else ''}</p>
<div class=flow>{flow}</div>
{bench_section(bench)}
{live_section(live, demo_url)}
</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", default="", help="the Autopilot code repository URL")
    parser.add_argument("--demo-url", default="", help="the demo repository URL, for PR links")
    parser.add_argument("--out", default=str(ROOT / "site" / "index.html"))
    args = parser.parse_args(argv)
    try:
        page = render(load(ROOT / "bench" / "results.json"), load(ROOT / "metrics" / "metrics.json"),
                      args.repo_url, args.demo_url)
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print(f"[render_report] {error}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
