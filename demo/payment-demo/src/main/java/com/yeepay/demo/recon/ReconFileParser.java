package com.yeepay.demo.recon;

import com.yeepay.demo.common.Money;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Parses a channel reconciliation file: detail lines {@code D|orderNo|amount}, then one trailer line
 * {@code T|count|totalAmount}. The whole file is rejected when details and trailer disagree (P-008).
 */
public final class ReconFileParser {

    public List<ReconRecord> parse(List<String> lines) {
        if (lines == null || lines.isEmpty()) {
            throw new ReconFileException("empty reconciliation file");
        }
        String trailer = lines.get(lines.size() - 1);
        if (!trailer.startsWith("T|")) {
            throw new ReconFileException("missing trailer line");
        }
        List<ReconRecord> records = new ArrayList<>();
        BigDecimal sum = BigDecimal.ZERO.setScale(Money.SCALE);
        for (String line : lines.subList(0, lines.size() - 1)) {
            String[] cols = line.split("\\|", -1);
            if (cols.length != 3 || !"D".equals(cols[0])) {
                throw new ReconFileException("malformed detail line: " + line);
            }
            BigDecimal amount = Money.yuan(cols[2]);
            records.add(new ReconRecord(cols[1], amount));
            sum = sum.add(amount);
        }
        String[] tail = trailer.split("\\|", -1);
        if (tail.length != 3) {
            throw new ReconFileException("malformed trailer line: " + trailer);
        }
        if (Integer.parseInt(tail[1]) != records.size()) {
            throw new ReconFileException("detail count " + records.size() + " != trailer count " + tail[1]);
        }
        if (Money.yuan(tail[2]).compareTo(sum) != 0) {
            throw new ReconFileException("detail sum " + sum + " != trailer sum " + tail[2]);
        }
        return List.copyOf(records);
    }
}
