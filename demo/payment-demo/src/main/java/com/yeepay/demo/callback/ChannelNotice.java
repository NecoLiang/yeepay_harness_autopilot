package com.yeepay.demo.callback;

/** A payment result notice pushed by a channel; {@code noticeId} is the channel's idempotency key. */
public record ChannelNotice(String noticeId, String orderNo, String status) {
}
