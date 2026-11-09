# yeeHarness Autopilot — 实施计划与进度

> 决策：
> - 2026-11-09：融合成新产物，GitHub 演示仓，1 周内交付。
> - 2026-11-09 补充：**接单只走飞书**，功能推进在 IM 中完成；交付物按五段式写在 README（背景 / 价值 / 可验证成果 / 创新点 / 代码仓库）。

## 进度

| 项 | 状态 | 证据 |
|---|---|---|
| 安装 gh / lark-cli / dsh 0.2.1-rc.3，构建 dsh-superagent | ✅ | `dsh --version`；`~/src/dsh-superagent` 构建通过 |
| superagent 配置（3082，启用飞书 Source，promptMaxChars 300000）并启动 | ✅ | `scripts/dsh-superagent status` 退出码 3（等待账号配置） |
| yeeHarness 技能打包为团队技能，并写入运行中的 superagent | ✅ | prompts revision 2：4 个技能 + 3 段团队提示词 |
| 演示仓库：分账缺陷可复现，配有 AGENTS.md、CI、内置门禁 | ✅ | 0.10 → 0.09，1999.99 → 2000.00 |
| 交付门禁 + 业务规则（R-xxx）加载 | ✅ | 测试覆盖率 97% |
| 门禁基准 21 例 | ✅ | 拦截率 100%，误拦率 0% |
| 一键配置、上线、指标采集、结果页 | ✅ | 84 个测试 |
| 独立代码审查（10 项问题） | ✅ 已全部修复 | 回归测试已补 |
| 提交材料（README 五段式）、架构文档、演示脚本、操作员步骤 | ✅ | `README.md`、`docs/` |
| **操作员步骤**：GitHub agent 账号、飞书机器人、DeepSeek Key | ⏳ 需本人 | `docs/operator-steps.md` |
| `scripts/go_live.sh`、飞书实跑、采集数据、录屏 | ⏳ 等上一项完成 | `docs/demo-script.md` |
| 推送本仓库并部署结果页（GitHub Pages） | ⏳ 需确认仓库位置 | — |

## D1 风险验证结论

1. **技能格式是否兼容**：✅ 兼容。团队技能是「名称 → 正文」，正文前 120 字作为描述；`build_skills.py` 把 shared 文件内联成附录，已保存成功。
2. **worker 能否执行门禁、能否上报 blocked**：⏳ 需实跑确认。文档说明 worker 执行命令不需要审批，`orchestrator_report` 支持 `blocked`。兜底：CI 里会再跑一次同一门禁。
3. **模型**：⏳ 默认 `deepseek-official / deepseek-flash`，需要配置 API Key。

## 实跑时重点观察

- worker 是否先加载 `dsh-superagent-yeeharness` 再加载场景技能（面板里看 Executor Session 的工具调用）
- 尾差问题是否走 `human_action`，并且只问一次
- 门禁拦截后是否自行修正，而不是直接 ready
- 进化审批「同意」后是否追加了 gate-rules.json 提交

## 比赛后

GitLab Source（`glab`，约 3–5 天）→ 内部模型 → 与 Observe 双链路度量打通 → 在真实业务仓库用 observe 模式试运行。
