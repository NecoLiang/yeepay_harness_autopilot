# payment-demo

脱敏的支付分账示例服务，是 [yeeHarness Autopilot](https://github.com/) 的演示仓库：
团队在飞书群里 @机器人提需求，AI 成员在这个仓库里按 yeeHarness 流程修复并提交 PR。

| 模块 | 说明 | 相关规约 |
|---|---|---|
| `split` | 按比例分账 | P-001 金额精度 |
| `recon` | 渠道对账文件解析 | P-008 文件尾校验 |
| `callback` | 渠道回调处理 | P-003 幂等 / P-005 / P-006 |

```sh
mvn -B test                         # 单元测试
python3 .yeeharness/yh_verify.py    # yeeHarness 交付门禁（规约 + 测试）
```
