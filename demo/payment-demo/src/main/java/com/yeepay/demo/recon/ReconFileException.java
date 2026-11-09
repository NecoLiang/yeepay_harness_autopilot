package com.yeepay.demo.recon;

/** The reconciliation file must be rejected as a whole. */
public class ReconFileException extends RuntimeException {

    public ReconFileException(String message) {
        super(message);
    }
}
