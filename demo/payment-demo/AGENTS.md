# AGENTS.md — payment-demo

脱敏的支付分账示例服务，用于 yeeHarness Autopilot 演示。Java 17 + Maven，无外部依赖。

## 必须遵守

1. **流程**：任何改动先加载 yeeHarness 技能（`yeeharness` 路由技能会告诉你走哪个场景），按场景流程执行，不跳步。
2. **规约**：公共层 P-xxx / G-xxx 见 `yeeharness` 技能；本仓库业务层规约 R-xxx 见下文与 `.yeeharness/gate-rules.json`。冲突时业务层优先。
3. **交付门禁**：报告 ready 之前必须运行并通过：

   ```sh
   python3 .yeeharness/yh_verify.py --json .yeeharness/gate-report.json --markdown .yeeharness/gate-report.md
   ```

   退出码 0 才能报告 ready；把 `gate-report.md` 的内容贴进 PR 描述的「交付门禁」小节。不要提交 `gate-report.*`。
4. **测试**：`mvn -B test`。修复缺陷必须先写能复现缺陷的失败测试，再修复。

## 领域约定

- 金额单位为元，两位小数，全程 `BigDecimal`（`com.yeepay.demo.common.Money`）。
- 分账不变量：**各方分账金额之和必须严格等于订单金额**，清算系统依赖它做无差额结算。
- 对账文件入库前校验文件尾汇总（P-008），回调按通知号幂等（P-003）。

## 业务层规约（R-xxx）

<!-- 由进化捕获追加，编号只增不复用 -->
