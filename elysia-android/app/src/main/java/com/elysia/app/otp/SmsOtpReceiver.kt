package com.elysia.app.otp

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.provider.Telephony
import com.elysia.core.log.ElysiaLog
import com.elysia.core.otp.OtpExtractor

/**
 * Watches incoming SMS and extracts one-time passwords.
 * When an OTP is found it immediately auto-fills the currently focused
 * field in whatever app the user is in (via the accessibility service),
 * and shows a floating bubble as a fallback / manual tap target.
 */
class SmsOtpReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        if (!OtpPrefs.enabled(context)) return

        val otp = extractOtp(intent) ?: return
        ElysiaLog.i(TAG, "OTP detected: $otp")

        OtpPrefs.setPending(context, otp)
        OtpOverlayController.show(context, otp)

        // Give the current app a moment to settle, then fill the focused
        // field automatically. If the fill succeeds the bubble dismisses
        // itself; otherwise the bubble stays for a manual tap.
        Handler(Looper.getMainLooper()).postDelayed({
            ElysiaLog.i(TAG, "auto-fill attempt: $otp")
            OtpAutofillHelper.fillFocusedField(context, otp)
        }, AUTO_FILL_DELAY_MS)
    }

    private fun extractOtp(intent: Intent): String? {
        for (message in Telephony.Sms.Intents.getMessagesFromIntent(intent)) {
            val body = message?.displayMessageBody ?: message?.messageBody ?: continue
            val code = OtpExtractor.extract(body)
            if (code != null) return code
        }
        return null
    }

    companion object {
        private const val TAG = "SmsOtpReceiver"
        private const val AUTO_FILL_DELAY_MS = 1500L
    }
}