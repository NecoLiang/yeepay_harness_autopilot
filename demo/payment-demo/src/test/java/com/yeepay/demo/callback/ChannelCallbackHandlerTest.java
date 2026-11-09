package com.yeepay.demo.callback;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class ChannelCallbackHandlerTest {

    @Test
    void appliesNoticeOnce() {
        ChannelCallbackHandler handler = new ChannelCallbackHandler();
        assertTrue(handler.handle(new ChannelNotice("N1", "O1", "SUCCESS")));
        assertFalse(handler.handle(new ChannelNotice("N1", "O1", "SUCCESS")));
        assertEquals("SUCCESS", handler.statusOf("O1"));
    }

    @Test
    void unknownStatusStaysProcessing() {
        ChannelCallbackHandler handler = new ChannelCallbackHandler();
        handler.handle(new ChannelNotice("N2", "O2", "TIMEOUT"));
        assertEquals("PROCESSING", handler.statusOf("O2"));
    }

    @Test
    void terminalStatusIsNotOverwritten() {
        ChannelCallbackHandler handler = new ChannelCallbackHandler();
        handler.handle(new ChannelNotice("N3", "O3", "SUCCESS"));
        handler.handle(new ChannelNotice("N4", "O3", "UNKNOWN"));
        assertEquals("SUCCESS", handler.statusOf("O3"));
    }
}
