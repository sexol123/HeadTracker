package com.headtracker.cam

import android.content.Context
import android.content.SharedPreferences

data class StreamSettings(
    val port: Int,
    val width: Int,
    val height: Int,
    val fps: Int,
    val quality: Int,
    val backCamera: Boolean,
)

class Prefs(context: Context) {
    private val sp: SharedPreferences =
        context.getSharedPreferences("headtrackercam", Context.MODE_PRIVATE)

    fun load(): StreamSettings = StreamSettings(
        port = sp.getInt(KEY_PORT, 8080),
        width = sp.getInt(KEY_WIDTH, 640),
        height = sp.getInt(KEY_HEIGHT, 480),
        fps = sp.getInt(KEY_FPS, 30),
        quality = sp.getInt(KEY_QUALITY, 70),
        backCamera = sp.getBoolean(KEY_BACK_CAMERA, true),
    )

    fun save(s: StreamSettings) {
        sp.edit()
            .putInt(KEY_PORT, s.port)
            .putInt(KEY_WIDTH, s.width)
            .putInt(KEY_HEIGHT, s.height)
            .putInt(KEY_FPS, s.fps)
            .putInt(KEY_QUALITY, s.quality)
            .putBoolean(KEY_BACK_CAMERA, s.backCamera)
            .apply()
    }

    companion object {
        private const val KEY_PORT = "port"
        private const val KEY_WIDTH = "width"
        private const val KEY_HEIGHT = "height"
        private const val KEY_FPS = "fps"
        private const val KEY_QUALITY = "quality"
        private const val KEY_BACK_CAMERA = "back_camera"
    }
}