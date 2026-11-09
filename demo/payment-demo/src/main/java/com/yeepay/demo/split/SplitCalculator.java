package com.yeepay.demo.split;

import com.yeepay.demo.common.Money;
import java.math.BigDecimal;
import java.util.List;

/**
 * Splits an order amount among merchants by ratio.
 *
 * <p>Callers rely on one invariant: the shares always add up to the order amount, so the clearing
 * system can settle the order without a difference.
 */
public final class SplitCalculator {

    /** Returns one share per rule, in rule order. */
    public List<SplitShare> split(BigDecimal orderAmount, List<SplitRule> rules) {
        Money.requireValid(orderAmount, "orderAmount");
        if (rules == null || rules.isEmpty()) {
            throw new IllegalArgumentException("rules must not be empty");
        }
        double total = orderAmount.doubleValue();
        return rules.stream()
                .map(rule -> {
                    double share = total * rule.ratio().doubleValue();
                    double rounded = Math.round(share * 100) / 100.0;
                    return new SplitShare(rule.merchantNo(), BigDecimal.valueOf(rounded).setScale(Money.SCALE));
                })
                .toList();
    }
}
