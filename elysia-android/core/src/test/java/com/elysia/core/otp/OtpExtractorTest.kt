package com.elysia.core.otp

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class OtpExtractorTest {

    @Test
    fun `extracts otp after hint word`() {
        assertEquals("123456", OtpExtractor.extract("Your OTP is 123456. Do not share it."))
        assertEquals("482913", OtpExtractor.extract("Verification code: 482913"))
        assertEquals("1234", OtpExtractor.extract("Your one-time pin is 1234"))
    }

    @Test
    fun `extracts code alone as fallback`() {
        assertEquals("998877", OtpExtractor.extract("998877"))
        assertEquals("12345678", OtpExtractor.extract("Your code is 12345678"))
    }

    @Test
    fun `picks code nearest hint word when present`() {
        assertEquals("1234", OtpExtractor.extract("Codes: 1234 and 112233 and 55"))
    }

    @Test
    fun `returns null when no code present`() {
        assertNull(OtpExtractor.extract("Hello, this is a plain message."))
        assertNull(OtpExtractor.extract(""))
    }

    @Test
    fun `ignores payment messages without hint`() {
        assertNull(OtpExtractor.extract("Payment of 5000 received. Thanks!"))
    }

    @Test
    fun `detects app name after from at or for`() {
        assertEquals("Paytm", OtpExtractor.appName("OTP from Paytm: 123456"))
        assertEquals("Bank", OtpExtractor.appName("OTP for Bank: 987654"))
        assertEquals("ACME Wallet", OtpExtractor.appName("Code at ACME Wallet is 112233"))
        assertNull(OtpExtractor.appName("Your Paytm code is 123456"))
    }
}