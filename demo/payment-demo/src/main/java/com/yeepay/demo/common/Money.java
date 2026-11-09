package com.yeepay.demo.common;

import java.math.BigDecimal;
import java.math.RoundingMode;

/** Amount helpers. Yuan amounts carry two decimals; all arithmetic stays in BigDecimal (P-001). */
public final class Money {

    public static final int SCALE = 2;

    private Money() {
    }

    /** Parses a yuan amount from its string form; fails fast on null or blank input (P-002). */
    public static BigDecimal yuan(String text) {
        if (text == null || text.isBlank()) {
            throw new IllegalArgumentException("amount must not be blank");
        }
        return new BigDecimal(text.trim()).setScale(SCALE, RoundingMode.UNNECESSARY);
    }

    /** Requires a non-null, non-negative amount with at most two decimals. */
    public static BigDecimal requireValid(BigDecimal amount, String name) {
        if (amount == null) {
            throw new IllegalArgumentException(name + " must not be null");
        }
        if (amount.signum() < 0) {
            throw new IllegalArgumentException(name + " must not be negative");
        }
        return amount.setScale(SCALE, RoundingMode.UNNECESSARY);
    }
}
