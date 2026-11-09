# yeeHarness Autopilot

> 团队在飞书群里 @它提需求，它按 yeeHarness 支付研发流程把活干完：PR 只有过了门禁才算交付，这次踩过的坑会变成下一次的门禁规则。

公式：**Model + Harness + 行业规约**。
- DeepSeek dsh-superagent 解决「何时、为谁、由谁做」：接单、授权、派工、回到原对话交付。
- yeeHarness 解决「怎么做对」：分场景流程、支付规约、完成门禁、自进化。

---

## 1. 开发背景

**yeeHarness 已经解决了「AI 写代码怎么写对」，但只服务坐在 IDE 前的那个人。**
yeeHarness 是易宝的 AI Coding 工作流，支持 Claude Code、Codex、OpenCode 和 WorkBuddy。它有六个研发场景，内置支付四道保护和 P-xxx 规约库，用 Stop hook 执行完成门禁，并通过进化捕获沉淀团队经验。它的前提是「一个人在终端里主动触发」，这带来三个限制：

- **需求在 IM 里，执行在 IDE 里。** 业务、测试、运营在飞书里提的问题，要先被某个研发看到、理解、转述，再由他打开终端去做，中间的等待和信息损耗都由人承担。
- **团队的经验只能在个人会话中生效。** 门禁和规约只在有人主动使用 yeeHarness 时起作用。
- **AI 的注意力成本不可见。** AI 打扰了多少次人、人花了多少注意力，没有度量。

**DeepSeek 于 2026-10-31 开源了 dsh-superagent。** 它是运行在 DeepSeek Harness 上的主动式编码 agent，监听 GitHub 和飞书，被允许的人 @它之后，它开单、在独立会话和目录里干活、回到原对话交付。它的核心原则是「尽量少占用人的注意力，尽量多给价值」，与 yeeHarness「能自查的不问、能点选的不打字」完全一致。但它是**行业中立**的：执行器只有一段通用提示词，不知道金额为什么不能用 double，也不知道对账文件为什么要校验文件尾。

两者恰好互补：superagent 有「团队成员」的身体，yeeHarness 有「支付研发」的大脑。本项目把它们接在一起。

## 2. 希望达到的价值

| 对象 | 价值 | 如何衡量（见第 3 节） |
|---|---|---|
| 提需求的人（业务、测试、研发） | 在飞书里一句话提需求，拿到的是可评审的 PR，不用切工具，也不用等人转述 | 需求到可评审 PR 的时长 |
| 研发团队 | 支付红线变成**机械执行**，不再依赖个人自觉：违规写法无法以 ready 交付 | 门禁对错误写法的拦截率、对正确改动的误拦率 |
| 团队知识 | 一次缺陷沉淀成一条业务规则，在飞书审批后**立即对所有后续工单生效**，团队对同类问题「免疫」 | 同一写法加规则前通过、加规则后被拦截 |
| 管理者 | AI 占用的人的注意力**第一次可度量**：每单机器人发了几条消息、人回了几条 | 每单机器人发言、每单人工发言 |
| yeeHarness 本身 | 从个人 copilot 升级为团队 AI 成员；IDE 内的用法不变，规约仍只有一份 | 场景技能由原仓库自动打包，零改动 |

## 3. 可验证成果

所有数字都能用仓库里的命令复现；没有实测的部分会直接写明「待实跑」，不会用估算数字填空。

### 3.1 交付门禁基准（已完成，可复现）

`python bench/run_bench.py`：在演示仓库上应用 21 个候选改动，分别跑门禁。

| 指标 | 结果 |
|---|---|
| 用例数 | 21（12 个错误写法 + 9 个正确改动） |
| 错误写法拦截率 | **100%**（12/12） |
| 正确改动误拦率 | **0%**（0/9） |
| 进化规则生效验证 | 同一段 `HALF_UP` 分账代码：R-001 加入前**通过**，加入后**被拦截** |

逐条结果见 [bench/results.md](bench/results.md)。基准第一次运行时发现了门禁的一个真实漏洞：变量名不含 amount 的 BigDecimal 用 `equals` 比较时没有被拦截，即 `paid.equals(refunded)` 这种写法。现已改为按类型识别，并补充了测试。

> 用例由本项目编写，覆盖 yeeHarness 规约针对的典型错误写法与对应的正确写法。它衡量规则是否按设计生效，不代表对任意代码库的检出率。

### 3.2 演示缺陷（已复现）

`demo/payment-demo` 是脱敏的分账服务，按比例分账时用 double 计算，并对每一份单独四舍五入：

| 订单金额 | 三方比例 0.3333 / 0.3333 / 0.3334 | 合计 | 差额 |
|---|---|---|---|
| 0.10 | 0.03 / 0.03 / 0.03 | 0.09 | **少 1 分** |
| 1999.99 | 666.60 / 666.60 / 666.80 | 2000.00 | **多 1 分** |

原有的 10 个单元测试全部通过，缺陷被测试漏过，和真实情况一样。

### 3.3 工程质量（已完成）

- 84 个测试全部通过（单元 + 集成，含对 Management API 的端到端模拟），总覆盖率 **94%**
- 独立代码审查发现 10 项问题，均已修复并补回归测试。例如：`++i` 行被误认为文件头导致漏检、含空格或中文的路径被跳过、`getPaidAmount().equals` 漏检、PR 可以修改 CI 自己的门禁：`.venv/bin/pytest --cov=gate --cov=scripts`
- 已在本机实际接入：yeeHarness 的 4 个技能和 3 段团队提示词已保存进运行中的 dsh-superagent（prompts revision 2）

### 3.4 飞书实跑（待操作员完成账号步骤后运行）

完成 [docs/operator-steps.md](docs/operator-steps.md) 后，按 [docs/demo-script.md](docs/demo-script.md) 在飞书演示群里实跑。然后：

```sh
python scripts/collect_metrics.py   # 从 dsh-superagent 状态库只读采集
python scripts/render_report.py --repo-url <本仓库地址> --demo-url <演示仓库地址>
```

采集指标：工单数、需求到可评审 PR 的中位时长、每单机器人发言条数、每单人工发言条数、接单/忽略决策数。

### 3.5 体验地址

- 结果页 `site/index.html`：由上面两个 JSON 生成，可直接部署到 GitHub Pages
- 演示仓库：`https://github.com/<agent 账号>/payment-demo`，含 agent 提交的 PR 与门禁报告
- 飞书演示群：评委入群后 @机器人即可体验

## 4. 核心创新点

1. **把方法论接到编排层上，从个人 copilot 变成团队 AI 成员**
   superagent 负责接单、授权、派工和交付，yeeHarness 负责执行方法。`build_skills.py` 直接打包 yeeHarness 原仓库的技能，并叠加「无人值守适配层」，把「可视化选择」映射为结构化提问，把 worktree 映射为工单目录，把「合并」映射为 PR。**yeeHarness 原仓库零改动**，IDE 内用法不变，规约只有一份。

2. **以 IM 为原生入口的人机协作，把注意力当作一等指标**
   飞书里接单、确认、提问、交付全部回到原话题。提问一次只问一个，带选项和推荐项，回一个词就能答。资金类取舍（比如尾差归谁）必须问人，其余都自查。每单的机器人发言和人工发言都被采集，「省人的注意力」第一次可以度量。

3. **可执行的交付门禁是 ready 的唯一依据**
   支付规约在这里变成机械检查：P-001 浮点金额、未指定舍入、按类型识别的 `equals` 比较；P-002 空值兜底为 0；P-007 日志泄露敏感信息；G-003 未归类的骨架代码；以及测试。退出码不为 0 就不能报告 ready，只能是 draft。同一个门禁在 agent 工作目录和 GitHub CI 各跑一次。CI 使用**基线分支**上的门禁脚本和规则，PR 无法削弱检查它的门禁。门禁报告原文贴进 PR。

4. **进化闭环在 IM 里完成，审批即生效**
   缺陷修好后，agent 起草业务规则 R-xxx（正则，并用这次的错误写法验证能命中）→ 在飞书交付消息末尾附一句审批邀请，不阻塞交付 → 有人回复「同意 R-001」后，消息经订阅回到同一工单，写入 `.yeeharness/gate-rules.json` → 门禁立即对所有后续工单生效。公共层 P/G 规则只提建议，仍由 Harness Owner 在 yeeharness 仓库审批，保持分层。

5. **默认安全的权限边界**
   agent 使用独立的 GitHub 账号和飞书 bot（严格 bot 模式，不能代表任何个人）。GitHub 侧准入名单为空：只交付、不接单。工作在独立 worktree 中进行，从不直接合并。

## 5. 代码仓库

| 内容 | 位置 |
|---|---|
| 本项目 | 本仓库（`yeeharness-autopilot`） |
| 演示仓库 | `demo/payment-demo`，由 `scripts/go_live.sh` 发布到 `github.com/<agent 账号>/payment-demo` |
| yeeHarness（方法论来源） | `gitlab.yeepay.com/yeehub/yeeharness`，本项目不改动它 |
| dsh-superagent（编排层） | `github.com/deepseek-ai/dsh-superagent-prototype`（MIT） |

```
yeeharness-autopilot/
├── team/                 无人值守适配层、路由技能、三段团队提示词（源文件）
├── scripts/
│   ├── build_skills.py   yeeHarness 技能 → dsh 团队技能包 dist/prompts.json
│   ├── apply_settings.py 通过 Management API 写入飞书来源、准入策略、执行器、提示词
│   ├── install_wrappers.sh  agent 账号的 CLI 包装（不含任何密钥）
│   ├── go_live.sh        账号就绪后一条命令上线
│   ├── collect_metrics.py   实跑指标采集（只读）
│   └── render_report.py  结果页 site/index.html
├── gate/yh_verify.py     交付门禁（纯标准库，agent、CI、本地通用）
├── bench/                门禁基准用例与结果
├── demo/payment-demo/    脱敏分账服务（预埋缺陷、AGENTS.md、CI）
├── tests/                84 个测试
└── docs/                 架构、操作员步骤、演示脚本
```

## 快速开始

```sh
python3 -m venv .venv && .venv/bin/pip install pytest pytest-cov
.venv/bin/pytest                      # 84 个测试
.venv/bin/python bench/run_bench.py   # 门禁基准
```

上线步骤见 [docs/operator-steps.md](docs/operator-steps.md)，架构见 [docs/architecture.md](docs/architecture.md)。
