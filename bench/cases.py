"""Benchmark cases for the yeeHarness delivery gate.

Each case is one candidate change to ``demo/payment-demo``: the files it writes, the business
rules in force, and whether the gate is expected to block it. ``bad`` cases are the mistakes the
yeeHarness rules exist for; ``good`` cases are correct changes that must not be blocked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CALC = "src/main/java/com/yeepay/demo/split/SplitCalculator.java"
CALC_TEST = "src/test/java/com/yeepay/demo/split/SplitCalculatorTest.java"
REFUND = "src/main/java/com/yeepay/demo/split/RefundSplitter.java"


@dataclass(frozen=True)
class Case:
    name: str
    expect: str  # "block" or "pass"
    rule: str  # the rule the case exercises, for the per-rule table
    files: dict[str, str]
    business_rules: tuple[dict[str, str], ...] = ()
    run_tests: bool = False
    note: str = ""


def calculator(body: str, imports: str = "") -> str:
    return f"""package com.yeepay.demo.split;

import com.yeepay.demo.common.Money;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
{imports}
public final class SplitCalculator {{

    public List<SplitShare> split(BigDecimal orderAmount, List<SplitRule> rules) {{
        Money.requireValid(orderAmount, "orderAmount");
        if (rules == null || rules.isEmpty()) {{
            throw new IllegalArgumentException("rules must not be empty");
        }}
{body}
    }}
}}
"""


GOOD_FIX = calculator("""        List<SplitShare> shares = new ArrayList<>();
        BigDecimal allocated = BigDecimal.ZERO.setScale(Money.SCALE, RoundingMode.UNNECESSARY);
        for (int i = 0; i < rules.size(); i++) {
            SplitRule rule = rules.get(i);
            BigDecimal amount = i == rules.size() - 1
                    ? orderAmount.subtract(allocated)
                    : orderAmount.multiply(rule.ratio()).setScale(Money.SCALE, RoundingMode.DOWN);
            allocated = allocated.add(amount);
            shares.add(new SplitShare(rule.merchantNo(), amount));
        }
        return List.copyOf(shares);""")

GOOD_TEST = """package com.yeepay.demo.split;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;

class SplitCalculatorTest {

    private final SplitCalculator calculator = new SplitCalculator();

    @Test
    void sharesAlwaysAddUpToOrderAmount() {
        for (String amount : new String[] {"0.10", "100.00", "1999.99", "0.01"}) {
            List<SplitShare> shares = calculator.split(new BigDecimal(amount), List.of(
                    new SplitRule("M1", new BigDecimal("0.3333")),
                    new SplitRule("M2", new BigDecimal("0.3333")),
                    new SplitRule("M3", new BigDecimal("0.3334"))));
            BigDecimal sum = shares.stream().map(SplitShare::amount).reduce(BigDecimal.ZERO, BigDecimal::add);
            assertEquals(0, sum.compareTo(new BigDecimal(amount)), amount);
        }
    }
}
"""

FAILING_TEST = GOOD_TEST.replace('assertEquals(0, sum.compareTo(new BigDecimal(amount)), amount);',
                                 'assertEquals(0, sum.compareTo(new BigDecimal(amount).add(BigDecimal.ONE)), amount);')

TAIL_RULE = {"id": "R-001", "severity": "block", "title": "分账尾差必须显式分配给最后一方",
             "pattern": r"RoundingMode\.HALF_UP"}


def refund(line: str) -> str:
    return f"""package com.yeepay.demo.split;

import java.math.BigDecimal;
import java.math.RoundingMode;

public final class RefundSplitter {{

    public BigDecimal refundable(BigDecimal paid, BigDecimal refunded) {{
{line}
    }}
}}
"""


CASES: tuple[Case, ...] = (
    # ---- mistakes the gate must block ----
    Case("double 计算分账（原始缺陷写法）", "block", "P-001", {CALC: calculator("""        double total = orderAmount.doubleValue();
        return rules.stream()
                .map(r -> new SplitShare(r.merchantNo(), BigDecimal.valueOf(Math.round(total * r.ratio().doubleValue() * 100) / 100.0)))
                .toList();""")}),
    Case("BigDecimal 用 double 字面量构造", "block", "P-001", {CALC: calculator("""        BigDecimal third = new BigDecimal(0.3333);
        return rules.stream().map(r -> new SplitShare(r.merchantNo(), orderAmount.multiply(third)
                .setScale(Money.SCALE, RoundingMode.DOWN))).toList();""")}),
    Case("setScale 未指定舍入模式", "block", "P-001", {CALC: calculator("""        return rules.stream().map(r -> new SplitShare(r.merchantNo(),
                orderAmount.multiply(r.ratio()).setScale(2))).toList();""")}),
    Case("金额用 equals 比较", "block", "P-001", {REFUND: refund("""        if (paid.equals(refunded)) {
            return BigDecimal.ZERO.setScale(2, RoundingMode.UNNECESSARY);
        }
        return paid.subtract(refunded);""")}),
    Case("float 承载手续费", "block", "P-001", {REFUND: refund("""        float feeAmount = 0.6f;
        return paid.subtract(refunded).subtract(new BigDecimal(String.valueOf(feeAmount)));""")}),
    Case("金额空值兜底为 0", "block", "P-002", {REFUND: refund("""        BigDecimal done = refunded == null ? BigDecimal.ZERO : refunded;
        return paid.subtract(done);""")}),
    Case("Optional 兜底为 0", "block", "P-002", {REFUND: refund("""        return paid.subtract(java.util.Optional.ofNullable(refunded).orElse(BigDecimal.ZERO));""")}),
    Case("日志明文打印卡号", "block", "P-007", {REFUND: refund("""        String cardNo = "6222020000000000";
        System.out.println("refund to cardNo " + cardNo);
        return paid.subtract(refunded);""")}),
    Case("遗留未归类 TODO", "block", "G-003", {REFUND: refund("""        // TODO 部分退款时手续费怎么退
        return paid.subtract(refunded);""")}),
    Case("遗留 UnsupportedOperationException 骨架", "block", "G-003", {REFUND: refund("""        throw new UnsupportedOperationException("not yet");""")}),
    Case("修复后测试未通过", "block", "tests", {CALC: GOOD_FIX, CALC_TEST: FAILING_TEST}, run_tests=True),
    Case("违反进化出的业务规则 R-001", "block", "R-001", {CALC: calculator("""        return rules.stream().map(r -> new SplitShare(r.merchantNo(),
                orderAmount.multiply(r.ratio()).setScale(Money.SCALE, RoundingMode.HALF_UP))).toList();""")},
         business_rules=(TAIL_RULE,), note="同样代码在 R-001 未加入前会通过，见下一条"),
    # ---- correct changes the gate must pass ----
    Case("R-001 加入前的同一写法", "pass", "R-001", {CALC: calculator("""        return rules.stream().map(r -> new SplitShare(r.merchantNo(),
                orderAmount.multiply(r.ratio()).setScale(Money.SCALE, RoundingMode.HALF_UP))).toList();""")},
         note="证明 R-001 的拦截来自进化出的业务规则，而非内置规则"),
    Case("正确修复：尾差归最后一方 + 测试", "pass", "tests", {CALC: GOOD_FIX, CALC_TEST: GOOD_TEST}, run_tests=True),
    Case("正确修复（仅静态规则）", "pass", "P-001", {CALC: GOOD_FIX, CALC_TEST: GOOD_TEST}),
    Case("compareTo 比较金额", "pass", "P-001", {REFUND: refund("""        if (paid.compareTo(refunded) == 0) {
            return BigDecimal.ZERO.setScale(2, RoundingMode.UNNECESSARY);
        }
        return paid.subtract(refunded);""")}),
    Case("空值快速失败", "pass", "P-002", {REFUND: refund("""        if (refunded == null) {
            throw new IllegalArgumentException("refunded must not be null");
        }
        return paid.subtract(refunded);""")}),
    Case("脱敏后打印卡号", "pass", "P-007", {REFUND: refund("""        String cardNo = "6222020000000000";
        System.out.println("refund to cardNo " + mask(cardNo));
        return paid.subtract(refunded);
    }

    private static String mask(String no) {
        return no.substring(0, 4) + "****" + no.substring(no.length() - 4);""")}),
    Case("已归类的骨架 [骨架:依赖]", "pass", "G-003", {REFUND: refund("""        // TODO [骨架:依赖] 等渠道退款手续费接口 v2 上线后接入
        return paid.subtract(refunded);""")}),
    Case("测试代码里使用 double", "pass", "P-001", {CALC_TEST: GOOD_TEST.replace(
        "    @Test\n    void shares", "    private static final double TOLERANCE = 0.0;\n\n    @Test\n    void shares")}),
    Case("仅修改文档", "pass", "docs", {"docs/split.md": "# 分账\n\n尾差归最后一方。\n"}),
)
