package com.yeepay.demo.callback;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Handles channel notices idempotently (P-003): a repeated notice id is acknowledged without being
 * applied again. Only whitelisted terminal statuses change an order; anything else keeps it
 * PROCESSING (P-005 / P-006).
 */
public final class ChannelCallbackHandler {

    private static final Set<String> TERMINAL = Set.of("SUCCESS", "FAILED");

    private final Set<String> handled = ConcurrentHashMap.newKeySet();
    private final Map<String, String> orderStatus = new ConcurrentHashMap<>();

    /** Returns true when the notice was applied, false when it was a duplicate. */
    public boolean handle(ChannelNotice notice) {
        if (!handled.add(notice.noticeId())) {
            return false;
        }
        String status = TERMINAL.contains(notice.status()) ? notice.status() : "PROCESSING";
        orderStatus.merge(notice.orderNo(), status, (current, next) -> TERMINAL.contains(current) ? current : next);
        return true;
    }

    public String statusOf(String orderNo) {
        return orderStatus.getOrDefault(orderNo, "PROCESSING");
    }
}
