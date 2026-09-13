package com.elysia.app.otp

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.elysia.core.log.ElysiaLog

/**
 * Accessibility service that can type/paste the detected OTP into the
 * currently focused input field of ANY app (SMS, banking, whatever the
 * user is currently using).
 */
class ElysiaAutofillService : AccessibilityService() {

    @Volatile
    private var fillRequested = false

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val code = intent.getStringExtra(EXTRA_OTP) ?: return
            ElysiaLog.i(TAG, "fill requested: $code")
            fillRequested = true
            performFill(code)
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        serviceInfo = serviceInfo.apply {
            eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
                AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED or
                AccessibilityEvent.TYPE_VIEW_FOCUSED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            notificationTimeout = 100
        }
        registerReceiver(
            receiver,
            IntentFilter(ACTION_FILL_OTP),
            if (Build.VERSION.SDK_INT >= 33) Context.RECEIVER_NOT_EXPORTED else 0
        )
        ElysiaLog.i(TAG, "autofill service connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Retry once the window is focused if a fill was requested.
        val req = fillRequested
        if (!req) return
        val code = rememberCode()
        if (code.isNotEmpty()) {
            performFill(code)
        }
    }

    override fun onInterrupt() {
        fillRequested = false
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(receiver) }
        super.onDestroy()
    }

    private fun performFill(code: String) {
        if (code.isEmpty()) {
            fillRequested = false
            return
        }
        val root = rootInActiveWindow ?: run {
            // Not in a window yet; the event callback will retry.
            return
        }
        val field = findEditableField(root) ?: run {
            ElysiaLog.i(TAG, "no editable field found yet")
            // Keep the request; retry on next window event.
            return
        }
        val args = BundleCompat()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, code)
        val ok = field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args.bundle)
        if (ok) {
            ElysiaLog.i(TAG, "OTP filled into field")
            OtpPrefs.clearPending(this)
            fillRequested = false
            // Tell the overlay bubble to go away; we filled the field.
            runCatching {
                sendBroadcast(
                    Intent(ACTION_FILL_DONE).setPackage(packageName)
                )
            }
        } else {
            ElysiaLog.w(TAG, "ACTION_SET_TEXT failed; retrying on next event")
        }
    }

    private fun findEditableField(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (root.isEditable) return root
        for (i in 0 until root.childCount) {
            val child = root.getChild(i) ?: continue
            val found = findEditableField(child)
            child.recycle()
            if (found != null) return found
        }
        return null
    }

    private fun rememberCode(): String = OtpPrefs.pending(this).first

    private class BundleCompat {
        private val b = android.os.Bundle()
        fun putCharSequence(key: String, value: CharSequence) = b.putCharSequence(key, value)
        val bundle: android.os.Bundle get() = b
    }

    companion object {
        private const val TAG = "ElysiaAutofill"
        const val ACTION_FILL_OTP = "com.elysia.app.action.FILL_OTP"
        const val ACTION_FILL_DONE = "com.elysia.app.action.FILL_DONE"
        const val EXTRA_OTP = "otp"
    }
}

/** Ask the accessibility service (if connected) to fill the currently focused field. */
object OtpAutofillHelper {
    fun fillFocusedField(context: Context, code: String) {
        context.sendBroadcast(
            Intent(ElysiaAutofillService.ACTION_FILL_OTP)
                .setPackage(context.packageName)
                .putExtra(ElysiaAutofillService.EXTRA_OTP, code)
        )
    }
}