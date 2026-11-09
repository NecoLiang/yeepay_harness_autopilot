package com.yeepay.demo.split;

import java.math.BigDecimal;
import java.util.Objects;

/** One party of a split and its ratio of the order amount, for example 0.3333. */
public record SplitRule(String merchantNo, BigDecimal ratio) {

    public SplitRule {
        Objects.requireNonNull(merchantNo, "merchantNo");
        Objects.requireNonNull(ratio, "ratio");
        if (ratio.signum() < 0) {
            throw new IllegalArgumentException("ratio must not be negative: " + merchantNo);
        }
    }
}
