package com.elysia.app.otp

import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings

/**
 * Manages the floating OTP bubble. Requires SYSTEM_ALERT_WINDOW permission.
 */
object OtpOverlayController {

    fun canDraw(context: Context): Boolean =
        Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(context)

    fun show(context: Context, code: String) {
        if (!canDraw(context)) return
        val intent = Intent(context, OtpOverlayService::class.java)
            .putExtra(OtpOverlayService.EXTRA_CODE, code)
        if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
    }

    fun hide(context: Context) {
        context.stopService(Intent(context, OtpOverlayService::class.java))
    }
}