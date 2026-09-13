package com.elysia.app.otp

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import com.elysia.app.R
import com.elysia.core.log.ElysiaLog

/**
 * Floating pill shown above all apps when an OTP arrives.
 * Tapping it copies the code to the clipboard and asks the accessibility
 * service to paste it into the currently focused field. It auto-dismisses
 * when the accessibility service reports the fill succeeded, or after the
 * timeout as a fallback.
 */
class OtpOverlayService : Service() {

    private var overlayView: View? = null
    private var code: String = ""
    private val dismissHandler = Handler(Looper.getMainLooper())

    private val fillDoneReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == ElysiaAutofillService.ACTION_FILL_DONE) {
                ElysiaLog.i(TAG, "fill done; dismissing bubble")
                dismiss()
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        registerReceiver(
            fillDoneReceiver,
            IntentFilter(ElysiaAutofillService.ACTION_FILL_DONE),
            if (Build.VERSION.SDK_INT >= 33) Context.RECEIVER_NOT_EXPORTED else 0
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        code = intent?.getStringExtra(EXTRA_CODE) ?: return START_NOT_STICKY
        startForeground(NOTIFICATION_ID, buildNotification(code))
        showBubble(code)
        dismissHandler.postDelayed({ dismiss() }, BUBBLE_TIMEOUT_MS)
        return START_STICKY
    }

    private fun buildNotification(code: String): Notification {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "OTP autofill",
                    NotificationManager.IMPORTANCE_HIGH
                )
            )
        }
        val contentIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, com.elysia.app.MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("OTP received")
            .setContentText("Code $code — tap the bubble to fill it in")
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .build()
    }

    private fun showBubble(code: String) {
        hideBubble()
        val wm = getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager
        val tv = TextView(this)
        tv.text = "  OTP: $code — tap to fill  "
        tv.textSize = 15f
        tv.setTextColor(Color.WHITE)
        tv.setTypeface(Typeface.DEFAULT_BOLD)
        tv.setBackgroundColor(0xCC1A73E8.toInt())
        tv.setPadding(28, 16, 28, 16)
        tv.setOnClickListener {
            ElysiaLog.i(TAG, "bubble tapped; copying $code")
            copyToClipboard(code)
            OtpAutofillHelper.fillFocusedField(this, code)
            dismiss()
        }

        val params = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT
        )
        val flags =
            if (Build.VERSION.SDK_INT >= 26)
                android.view.WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else android.view.WindowManager.LayoutParams.TYPE_PHONE
        val lp = android.view.WindowManager.LayoutParams(
            params.width,
            params.height,
            flags,
            android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
        lp.y = 140
        try {
            wm.addView(tv, lp)
            overlayView = tv
        } catch (e: Exception) {
            ElysiaLog.e(TAG, "overlay failed: ${e.message}")
        }
    }

    private fun copyToClipboard(code: String) {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("OTP", code))
    }

    private fun hideBubble() {
        overlayView?.let { v ->
            try {
                (getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager).removeView(v)
            } catch (_: Exception) {
            }
            overlayView = null
        }
    }

    private fun dismiss() {
        dismissHandler.removeCallbacksAndMessages(null)
        hideBubble()
        stopSelf()
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(fillDoneReceiver) }
        dismissHandler.removeCallbacksAndMessages(null)
        hideBubble()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "OtpOverlay"
        private const val CHANNEL_ID = "otp_channel"
        private const val NOTIFICATION_ID = 7
        private const val BUBBLE_TIMEOUT_MS = 45_000L
        const val EXTRA_CODE = "otp_code"
    }
}