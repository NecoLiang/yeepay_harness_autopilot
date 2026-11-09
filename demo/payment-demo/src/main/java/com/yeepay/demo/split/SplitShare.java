package com.yeepay.demo.split;

import java.math.BigDecimal;
import java.util.Objects;

/** The amount one merchant receives from a split, in yuan with two decimals. */
public record SplitShare(String merchantNo, BigDecimal amount) {

    public SplitShare {
        Objects.requireNonNull(merchantNo, "merchantNo");
        Objects.requireNonNull(amount, "amount");
    }
}
