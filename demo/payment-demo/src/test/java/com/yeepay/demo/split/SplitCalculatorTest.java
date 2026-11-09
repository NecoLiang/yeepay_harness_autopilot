package com.yeepay.demo.split;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;

class SplitCalculatorTest {

    private final SplitCalculator calculator = new SplitCalculator();

    @Test
    void splitsEvenlyBetweenTwoMerchants() {
        List<SplitShare> shares = calculator.split(new BigDecimal("100.00"), List.of(
                new SplitRule("M001", new BigDecimal("0.5")),
                new SplitRule("M002", new BigDecimal("0.5"))));

        assertEquals(new BigDecimal("50.00"), shares.get(0).amount());
        assertEquals(new BigDecimal("50.00"), shares.get(1).amount());
    }

    @Test
    void keepsRuleOrder() {
        List<SplitShare> shares = calculator.split(new BigDecimal("10.00"), List.of(
                new SplitRule("M002", new BigDecimal("0.2")),
                new SplitRule("M001", new BigDecimal("0.8"))));

        assertEquals("M002", shares.get(0).merchantNo());
        assertEquals(new BigDecimal("8.00"), shares.get(1).amount());
    }

    @Test
    void rejectsNullOrderAmount() {
        assertThrows(IllegalArgumentException.class,
                () -> calculator.split(null, List.of(new SplitRule("M001", BigDecimal.ONE))));
    }

    @Test
    void rejectsEmptyRules() {
        assertThrows(IllegalArgumentException.class, () -> calculator.split(new BigDecimal("1.00"), List.of()));
    }
}
