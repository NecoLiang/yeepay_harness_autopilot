yeeHarness 支付研发工作流（Autopilot 无人值守版）：接单后先读本技能，判定场景并加载对应场景技能，交付前必须过门禁。

# yeeHarness — 路由、规约与交付门禁

## 1. 判定场景（接单确认前完成）

| 请求特征 | 场景 | 加载技能 |
|---|---|---|
| 现有行为不符合预期：报错、数据不对、金额差异、偶发失败 | 缺陷修复 | `dsh-superagent-yeeharness-bugfix` |
| 修改或扩展已有功能：加校验、改规则、调整逻辑 | 旧需求迭代 | `dsh-superagent-yeeharness-iterate` |
| 全新的功能、接口或模块 | 新需求开发 | `dsh-superagent-yeeharness-feature` |
| 只要方案、评估或对比，不要代码 | 方案设计 | 不写代码：把方案写成 `docs/design/<名称>.md` 并开 PR，结尾附推荐方案 |

确认消息要写明场景和预期结果，例如：「按缺陷修复流程处理：让三方分账合计与订单金额严格一致，完成后发 PR。」场景无法判断时，按影响更小的场景处理，并在 PR 里说明。

## 2. 规约（两层都要遵守；冲突时业务层优先）

公共层（yeeHarness 规约登记表）：

{{RULES}}

业务层：仓库根 `AGENTS.md` 的 R-xxx，以及 `.yeeharness/gate-rules.json`。

## 3. 支付领域知识

{{PAYMENT_DOMAIN}}

## 4. 交付门禁（ready 的唯一依据）

```sh
GATE=.yeeharness/yh_verify.py; [ -f "$GATE" ] || GATE="{{GATE_FALLBACK}}"
python3 "$GATE" --json /tmp/$DSH_SUPERAGENT_NAME-gate.json --markdown /tmp/$DSH_SUPERAGENT_NAME-gate.md
```

- 退出码 0：通过，把 Markdown 报告贴进 PR「交付门禁」小节，才可以 `state=ready`。
- 退出码 1：被拦截。逐条修复后重跑。确实无法修复时，保留为 draft PR 并在 PR 写明原因，报告 `state=blocked`，`human_action` 写明需要人决定什么。
- 退出码 2：门禁本身无法运行（基线、配置错误）。修复环境；修不了就 `state=blocked`。
- 门禁只检查新增代码。存量问题如果是本次的根因，也要一并修掉。

## 5. PR 描述模板（yeeHarness 交付卡）

```markdown
## 背景
<飞书原始需求一句话 + 场景>

## yeeHarness 交付卡
### 归一化（缺陷修复）/ 需求卡片（迭代、新需求）
| 维度 | 内容 | 来源 |
### 根因与证据
### 影响面评估
### Delta
- MODIFIED / ADDED / UNCHANGED
### 决策记录
<通过飞书确认的决策：问题 → 回答 → 执行方式>
### 回归清单
- [x] 每一项都已实际验证

## 交付门禁
<粘贴门禁 Markdown 报告>

## 进化建议
<R-xxx 草案或「无」>
```

## 6. 进化闭环（规则缺口 → 飞书审批 → 门禁立即生效）

1. 判断这次的根因能否写成可检测的规则，口诀「换一个业务团队还成立吗」：
   - 成立：属于公共层 P/G。只在 PR「进化建议」里写草案，注明「需 Harness Owner 在 yeeharness 仓库审批」，不改公共库。
   - 不成立：属于业务层 R-xxx，在下一步发起审批。
2. 业务层草案包含 `id`（取 AGENTS.md 中最大编号 +1）、`title`、`pattern`（Python 正则，只匹配错误写法），可选 `unless`。用本次被修掉的错误代码验证 pattern 能命中，修复后的代码不能命中。
3. 不要为规则单独发起 `human_action`：`ready` 报告会清除未回答的问题，而规则审批不能阻塞交付。把提议写进 `ready` 报告的 summary 末尾，让交付消息多带一句，例如：「另：本次可沉淀为业务规约 R-001『分账尾差必须显式分配』，加入门禁后同类写法会被自动拦截，回复『同意 R-001』即纳入。」
4. 话题里有人回复同意时（这条消息会经订阅回到本工单）：在同一个 PR 追加一个提交，往 `.yeeharness/gate-rules.json` 的 `rules` 加入草案，并在 `AGENTS.md` 业务层规约下加一行；重跑门禁，把新规则对旧写法的命中证据贴进 PR 评论；然后再报告一次 `ready`，交付消息一句话说明规则已加入。
5. 在 PR 评论输出进化播报块：

```
╔═══════════ yeeHarness 进化捕获 ═══════════╗
  教训登记: <一句话>
  分层判定: 业务层（仅本业务适用）/ 公共层（待 Harness Owner 审批）
  提炼规则: R-xxx <一句话规则>
  写入文件: .yeeharness/gate-rules.json, AGENTS.md
  分发方式: 随本 PR 合并 → 门禁对全员即时生效
╚═══════════════════════════════════════════╝
```

6. 对方不同意或一直没回复：不改规则文件，也不再追问。
