## yeeHarness Autopilot

- 唯一的完成标准是 yeeHarness 交付门禁退出码为 0。命令见 `dsh-superagent-yeeharness` 技能。没通过门禁只能开 draft PR，并报告 `state=blocked`，不能用 `ready`。
- PR 描述使用 `dsh-superagent-yeeharness` 技能里的「yeeHarness 交付卡」模板，并包含门禁 Markdown 报告原文。
- 提交信息遵循 `<type>: <description>`，type 取 feat、fix、refactor、docs、test、chore、perf、ci 之一。
- 不提交门禁产物（`gate-report.*`）和临时文件。
