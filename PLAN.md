# yeeHarness Autopilot — 进度

> 决策记录：
> - 2026-11-09：做融合新产物，用 GitHub 演示仓，1 周内交付。
> - 2026-11-09：接单只走飞书；交付物按 README 五段式组织。
> - 2026-11-10：**不用 dsh，改用 Claude Code 自建编排器**（团队只有 Claude Code / Codex）。dsh-superagent 只作为设计参考。

| 项 | 状态 | 证据 |
|---|---|---|
| 编排器 `autopilot/`（飞书接入、准入、工单、Claude 无头会话、门禁、PR、回复） | ✅ | 102 个测试 |
| 交付门禁 + 业务规则（只增不减） + 基准 21 例 | ✅ | 拦截 12/12，误拦 0/9 |
| Claude Code 真实端到端（本地模式） | ✅ | 3.3 分钟交付；只问 1 个资金问题；进化出 R-001 并验证有效；共 $2.20；见 `evidence/` |
| 提交材料（README 五段式）、架构、演示脚本、操作员步骤 | ✅ | `README.md`、`docs/` |
| 操作员步骤：GitHub agent 账号、飞书机器人 | ⏳ 需本人 | `docs/operator-steps.md` |
| 飞书实跑、录屏 | ⏳ 等上一项完成 | `docs/demo-script.md` |
| 推送 GitHub 公开仓 + Pages | ⏳ 需要 `gh auth login`（你自己的账号） | — |

## 后续

Codex runner（`codex exec`，与 ClaudeRunner 同一接口）→ GitLab 发布（glab）→ 内部模型网关 → 在真实业务仓库试运行。
