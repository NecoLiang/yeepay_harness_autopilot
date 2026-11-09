package com.yeepay.demo.recon;

import java.math.BigDecimal;

/** One detail line of a channel reconciliation file. */
public record ReconRecord(String channelOrderNo, BigDecimal amount) {
}
