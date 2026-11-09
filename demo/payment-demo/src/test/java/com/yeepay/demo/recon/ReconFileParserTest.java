package com.yeepay.demo.recon;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.List;
import org.junit.jupiter.api.Test;

class ReconFileParserTest {

    private final ReconFileParser parser = new ReconFileParser();

    @Test
    void parsesConsistentFile() {
        List<ReconRecord> records = parser.parse(List.of("D|C001|10.00", "D|C002|0.01", "T|2|10.01"));
        assertEquals(2, records.size());
    }

    @Test
    void rejectsTruncatedFile() {
        assertThrows(ReconFileException.class, () -> parser.parse(List.of("D|C001|10.00", "T|2|10.01")));
    }

    @Test
    void rejectsSumMismatch() {
        assertThrows(ReconFileException.class, () -> parser.parse(List.of("D|C001|10.00", "T|1|10.01")));
    }
}
