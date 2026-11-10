# yeeHarness Autopilot

> 团队在飞书群里 @它提需求。它用 Claude Code 按 yeeHarness 支付研发流程把活干完，过了门禁才交 PR，并把这次踩过的坑变成下一次的门禁规则。

**Model + Harness + 行业规约**：Claude Code 负责写代码，yeeHarness 负责定规矩，Autopilot 负责把需求从飞书接进来、把结果送回飞书。设计上借鉴了 DeepSeek 于 2026-10-31 开源的 dsh-superagent，但**不依赖 dsh**，直接使用团队已有的 Claude Code。

---

## 1. 开发背景

**yeeHarness 已经解决了「AI 写代码怎么写对」，但只服务坐在 IDE 前的那个人。**
yeeHarness 是易宝的 AI Coding 工作流：六个研发场景、支付四道保护与 P-xxx 规约库、完成门禁、进化捕获。它的前提是有人在终端里主动输入 `/yeeHarness-code`，这带来三个问题：

- **需求在 IM 里，执行在 IDE 里。** 业务、测试、运营在飞书里提的问题，要先有研发看到、理解、转述，再打开终端去做。中间的等待和信息损耗都由人承担。
- **规约只在有人主动用的时候才生效。** 团队积累的门禁和经验，生效范围取决于个人习惯。
- **AI 占用了多少人的注意力，没有度量。** AI 打扰了几次人、让人回了几条消息，都是一笔糊涂账。

DeepSeek 开源的 dsh-superagent 给出了另一种形态：AI 作为团队成员，在 IM 里被 @，在后台干活，回到原对话交付。它的原则是「尽量少占用人的注意力，尽量多给价值」。不过它要求部署 dsh 运行时，执行层也是行业中立的。

本项目把这种「团队 AI 成员」的形态，用团队**已有的 Claude Code** 和**已有的 yeeHarness 技能**实现出来。

## 2. 希望达到的价值

| 对象 | 价值 | 如何衡量（见第 3 节） |
|---|---|---|
| 提需求的人 | 在飞书里一句话提需求，拿到的是可评审的 PR；不用切工具，也不用等人转述 | 需求到可评审 PR 的时长 |
| 研发团队 | 支付红线变成**机械执行**：违规写法无法交付；能自己修的问题不打扰人 | 门禁拦截率与误拦率；门禁退回次数（这些退回都没有打扰人） |
| 团队知识 | 一次缺陷沉淀为一条业务规则，在飞书里回复「同意」后**写入门禁**，团队对同类问题免疫 | 加规则前后，同一写法的门禁结果 |
| 管理者 | AI 占用的人的注意力**可度量**：每单机器人发几条、人回几条、花多少钱 | 每单发言条数、每单模型成本 |
| 现有投入 | 零新增运行时：沿用 Claude Code 登录态和已安装的 yeeHarness 技能；IDE 内用法不变 | — |

## 3. 可验证成果

所有数字都能用仓库里的命令复现。还没实测的部分会写明「待实跑」，不会用估算数字填空。

### 3.1 端到端实跑（Claude Code 真实运行，已完成）

在演示仓库上，用本地模式跑完整流水线。本地模式和飞书模式走同一条流水线，只是回复打印在终端里，不发到飞书。需求原文：

> 清算对账发现分账合计和订单金额对不上：0.10 元的订单三方按 0.3333/0.3333/0.3334 分账，合计只有 0.09；1999.99 的订单合计却是 2000.00。帮忙修一下。

| 时间 | 机器人在话题里说的话 | 背后发生的事 |
|---|---|---|
| 0:00 | 收到，我会按 yeeHarness 流程处理，完成后在这个话题里给你 PR。 | 开工单，建 worktree 和 Claude 会话 |
| 1:01 | 已定位原因：分账时每一方各自四舍五入，没有处理尾差……请确认给谁：**A. 最后一方（推荐）** B. 比例最大的一方 C. 平台方。回一个字母即可。 | Claude 加载 yeeHarness-bugfix，自己复现、定位根因，**先提交了失败的复现测试**，然后只问了一个资金决策问题 |
| 1:25 | （人回复：A） | 恢复同一个会话 |
| 3:18 | 已修复：分账各方金额之和现在总是严格等于订单金额……另：本次可沉淀为业务规约 R-001「分账份额禁止逐方独立舍入，尾差必须由一方承接」，回复「同意 R-001」即纳入。 | BigDecimal + 尾差归最后一方；交付门禁通过（规约 + 测试）后才交付 |

| 指标 | 结果 |
|---|---|
| 需求到可评审交付 | **3.3 分钟**（含人回答问题的 24 秒） |
| 机器人发言 | 3 条（确认、提问、交付） |
| 人追加的发言 | 1 条（一个字母） |
| 模型成本 | 2 次 Claude 运行，共 **$1.14** |

**进化闭环（同一工单继续实跑）：**

| 时间 | 话题 | 背后发生的事 |
|---|---|---|
| 4:07 | （人回复：同意 R-001） | 恢复同一个会话 |
| 5:26 | 已将 R-001 加入门禁，后续同类写法会被自动拦截。 | Claude 追加提交：`.yeeharness/gate-rules.json` 新增 R-001，pattern 为 `new\s+SplitShare\([^;]*\.setScale\(`；`AGENTS.md` 业务规约表加了一行；门禁重跑通过 |

独立验证：R-001 命中原始缺陷代码中的 `new SplitShare(…, BigDecimal.valueOf(rounded).setScale(Money.SCALE))`，在修复后的代码上**零命中**。

整单合计：机器人发言 4 条，人发言 2 条（「A」和「同意 R-001」），3 次 Claude 运行共 **$2.20**，提交 3 个：复现测试 → 修复 → 规则。
这次实跑中，Claude 第一次报告 ready 就通过了门禁，所以「门禁退回」这条路径没有在实跑中触发；它的行为由测试覆盖（`tests/test_engine.py`）。

实跑也暴露了一个问题：Claude 在需求之外**顺手加了「比例合计不为 1 就报错」的校验**。它在 PR 的「影响面评估」里如实写明了这一点，但这仍然是没被要求的行为变化。为此已在系统提示词里补了一条约束：需求之外的行为变化只写进 PR 的「后续建议」，不直接改。

Claude 写的 PR 描述、完整 diff、门禁报告和飞书话题记录都保存在 [evidence/](evidence/) 目录。

复现方法：`python -m autopilot --config autopilot.local.json ask "<需求>"`，然后 `reply <工单号> "A"`；`python scripts/collect_metrics.py --db ~/.yeeharness-autopilot/autopilot.sqlite` 输出上面的指标。

### 3.2 交付门禁基准（可复现）

`python bench/run_bench.py` 在演示仓库上应用 21 个候选改动，分别跑门禁：

| 指标 | 结果 |
|---|---|
| 错误写法拦截率 | **100%**（12/12） |
| 正确改动误拦率 | **0%**（0/9） |
| 进化规则生效 | 同一段 `HALF_UP` 写法：R-001 加入前**通过**，加入后**被拦截** |

逐条结果见 [bench/results.md](bench/results.md)。用例由本项目编写，衡量的是规则是否按设计生效，不代表对任意代码库的检出率。

### 3.3 工程质量

- **102 个测试**全部通过，总覆盖率 **93%**（`.venv/bin/pytest --cov=autopilot --cov=gate --cov=scripts`）。测试包括：真实 git worktree 和真实门禁配合脚本化的 Claude；用假的 `claude`、`lark-cli`、`gh` 可执行文件加一个真实的 bare 远端，测试子进程适配层。
- 一轮独立代码审查发现 10 个问题，已全部修复并补了回归测试。例如：`++i` 行被误认为文件头导致漏检；PR 可以修改 CI 自己的门禁。

### 3.4 飞书实跑（待操作员完成账号步骤后运行）

完成 [docs/operator-steps.md](docs/operator-steps.md)（GitHub agent 账号和飞书机器人，约 15 分钟）后，运行 `scripts/go_live.sh` 和 `python -m autopilot serve`，再按 [docs/demo-script.md](docs/demo-script.md) 在群里实跑。实跑数据用同一组脚本采集，填进结果页。

### 3.5 体验地址

- 结果页 `site/index.html`：由基准和实跑数据生成，部署到 GitHub Pages
- 演示仓库 `github.com/<agent 账号>/payment-demo`：包含 agent 提交的 PR 和门禁报告
- 飞书演示群：评委入群后 @机器人即可体验

## 4. 核心创新点

1. **团队 AI 成员，零新运行时。** Claude Code 在无头模式下运行（`claude -p`），每个工单有独立的 worktree 和一个会话。人在话题里回复，会用 `--resume` 回到同一个会话，上下文完整保留。yeeHarness 技能原样加载，规约只有一份，IDE 内的用法不变。
2. **报告协议：模型干活，编排器决定说什么。** Claude 不能直接发消息，每轮结束时只写一个结构化的报告文件（ready、question 或 blocked）。确认只发一次；一次只问一个问题，带选项和推荐项；只有门禁通过才交付；做不到就如实报告 blocked，并附草稿 PR。资金类取舍必须问人，其余的自己查。
3. **门禁退回不打扰人。** Claude 报告 ready 后，编排器独立跑门禁。不通过就把门禁报告退回同一个会话让它修，最多 2 轮，超过后如实报告 blocked。业务规则取基线与改动的并集：改动只能加强规则，不能削弱。CI 里用基线分支上的门禁再跑一次。
4. **进化闭环在 IM 里完成。** 修复后 Claude 起草业务规则（正则），并用这次被修掉的错误写法验证它能命中。交付消息末尾附一句审批邀请，不会阻塞交付。有人回复「同意 R-001」后，规则写入 `.yeeharness/gate-rules.json`，此后的工单都受它约束。
5. **默认安全的权限边界。** Claude 被禁止调用 `git push`、`gh`、`lark-cli`、`curl`；推送和开 PR 只由编排器用 agent 账号完成。飞书机器人工作在严格 bot 模式，不能代表任何个人。准入规则：只响应名单内、@了机器人的人。
6. **注意力和成本可度量。** 每条机器人消息、每条人工消息、每次 Claude 运行（包括成本）、每次门禁结果都记入事件日志，直接生成结果页。

## 5. 代码仓库

| 内容 | 位置 |
|---|---|
| 本项目 | 本仓库 `yeeharness-autopilot` |
| 演示仓库 | `demo/payment-demo`，由 `scripts/go_live.sh` 发布到 `github.com/<agent 账号>/payment-demo` |
| yeeHarness（方法论来源） | 易宝内部仓库 yeehub/yeeharness（内网，不公开），本项目不改动它 |
| 设计参考 | [deepseek-ai/dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype)（MIT），借鉴了注意力原则、准入和话题订阅、结构化提问、诚实交付 |

```
yeeharness-autopilot/
├── autopilot/            编排器（约 1100 行，纯标准库）
│   ├── feishu.py         lark-cli：事件流、成员、话题回复
│   ├── admission.py      准入：群 + 名单 + @；话题内追加
│   ├── engine.py         工单状态机：Claude → 报告 → 门禁 → PR → 回复
│   ├── claude.py         claude -p 无头运行，会话续接
│   ├── protocol.py       报告文件协议与各类提示
│   ├── gate.py           门禁调用与规则合并（只增不减）
│   ├── workspace.py      worktree、agent 账号推送与 PR
│   ├── store.py          SQLite：工单、输入、事件日志
│   └── prompts/system.md Autopilot 系统提示词（交互映射、报告格式、进化闭环）
├── gate/yh_verify.py     交付门禁（agent、CI、本地通用）
├── bench/                门禁基准
├── demo/payment-demo/    脱敏分账服务（预埋缺陷、AGENTS.md、CI）
├── scripts/              上线、度量、结果页、演示仓初始化
├── tests/                102 个测试（含 fakes/ 假的可执行文件）
└── docs/                 架构、操作员步骤、演示脚本
```

## 快速开始

```sh
python3 -m venv .venv && .venv/bin/pip install pytest pytest-cov
.venv/bin/pytest                                   # 102 个测试
.venv/bin/python bench/run_bench.py                # 门禁基准
bash scripts/init_demo_repo.sh ~/src/payment-demo  # 准备演示仓库
cp autopilot.config.example.json autopilot.local.json   # 本地模式只需 checkout 一项
.venv/bin/python -m autopilot --config autopilot.local.json ask "<需求>"
```
