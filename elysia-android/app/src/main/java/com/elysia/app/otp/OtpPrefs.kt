package com.elysia.app.otp

import android.content.Context
import android.content.SharedPreferences

/** Small preference holder for OTP feature state and the last detected code. */
object OtpPrefs {

    private const val FILE = "elysia_otp"
    private const val KEY_ENABLED = "otp_enabled"
    private const val KEY_PENDING = "otp_pending"
    private const val KEY_PENDING_AT = "otp_pending_at"

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun enabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, false)

    fun setEnabled(context: Context, value: Boolean) {
        prefs(context).edit().putBoolean(KEY_ENABLED, value).apply()
    }

    fun setPending(context: Context, code: String) {
        prefs(context).edit()
            .putString(KEY_PENDING, code)
            .putLong(KEY_PENDING_AT, System.currentTimeMillis())
            .apply()
    }

    fun pending(context: Context): Pair<String, Long> {
        val p = prefs(context)
        return (p.getString(KEY_PENDING, null) ?: "") to p.getLong(KEY_PENDING_AT, 0L)
    }

    fun clearPending(context: Context) {
        prefs(context).edit().remove(KEY_PENDING).remove(KEY_PENDING_AT).apply()
    }
}