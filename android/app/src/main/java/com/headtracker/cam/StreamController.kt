package com.headtracker.cam

import android.content.Context
import android.graphics.Bitmap
import android.os.Build
import android.os.PowerManager
import android.util.Log
import android.util.Size
import android.view.Surface
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import java.io.ByteArrayOutputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Owns CameraX capture + JPEG encoding + the WebSocket broadcast.
 * STRATEGY_KEEP_ONLY_LATEST guarantees the newest frame is always sent —
 * nothing queues up between camera and encoder, so end-to-end latency stays
 * at one frame duration plus encode/wifi time.
 */
class StreamController(
    private val context: android.content.Context,
    private val previewView: PreviewView,
    private val onStatus: (port: Int, clients: Int, encoderFps: Double) -> Unit,
    private val onError: (String) -> Unit,
) {
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val running = AtomicBoolean(false)

    // The camera is bound to a manual lifecycle that stays RESUMED forever,
    // so backgrounding the app (screen off, home button) does NOT kill the
    // stream — the phone keeps serving the desktop.
    private val cameraLifecycle = AlwaysOnLifecycleOwner()

    private var cameraProvider: ProcessCameraProvider? = null
    private var camera: Camera? = null
    private var server: WssServer? = null
    private var activeSettings: StreamSettings? = null
    private var wakeLock: PowerManager.WakeLock? = null

    private var lastEncodeTime = 0L
    private var encFps = 0.0

    fun startCamera() {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            try {
                cameraProvider = future.get()
                bind()
            } catch (e: Exception) {
                onError("Camera init failed: ${e.message}")
            }
        }, ContextCompat.getMainExecutor(context))
    }

    fun setStreaming(on: Boolean, s: StreamSettings) {
        if (on == running.get()) return
        running.set(on)
        activeSettings = s
        if (on) {
            startServer(s)
            acquireWakeLock()
        } else {
            stopServer()
            releaseWakeLock()
        }
        bind()
    }

    fun setTorch(on: Boolean) {
        try {
            camera?.cameraControl?.enableTorch(on)
        } catch (e: Exception) {
            onError("Torch failed: ${e.message}")
        }
    }

    fun torchSupported(): Boolean = camera?.cameraInfo?.hasFlashUnit() == true

    /** Front/back switch: rebinds the camera use case. */
    fun switchLens(back: Boolean, s: StreamSettings) {
        activeSettings = s.copy(backCamera = back)
        bind()
    }

    fun release() {
        running.set(false)
        stopServer()
        releaseWakeLock()
        try {
            cameraProvider?.unbindAll()
        } catch (_: Exception) {
        }
        camera = null
    }

    fun shutdown() {
        release()
        executor.shutdownNow()
    }

    private fun bind() {
        val provider = cameraProvider ?: return
        val settings = activeSettings
        val selector = if (settings?.backCamera ?: true) CameraSelector.DEFAULT_BACK_CAMERA
        else CameraSelector.DEFAULT_FRONT_CAMERA

        val useCases = mutableListOf<androidx.camera.core.UseCase>()
        val preview = Preview.Builder().build().also {
            it.surfaceProvider = previewView.surfaceProvider
        }
        useCases.add(preview)

        if (running.get() && settings != null) {
            val analysis = ImageAnalysis.Builder()
                .setResolutionSelector(
                    androidx.camera.core.resolutionselector.ResolutionSelector.Builder()
                        .setResolutionStrategy(
                            androidx.camera.core.resolutionselector.ResolutionStrategy(
                                Size(settings.width, settings.height),
                                androidx.camera.core.resolutionselector.ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER,
                            ),
                        )
                        .build(),
                )
                .setTargetRotation(displayRotation())
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
                .also { it.setAnalyzer(executor) { image -> analyze(image, settings) } }
            useCases.add(analysis)
            Log.i(TAG, "Stream on: ${settings.width}x${settings.height}@${settings.fps} "
                    + "quality=${settings.quality} lens="
                    + (if (settings.backCamera) "back" else "front")
                    + " rotation=${displayRotation()}")
        }

        try {
            provider.unbindAll()
            camera = provider.bindToLifecycle(
                cameraLifecycle,
                selector,
                *useCases.toTypedArray(),
            )
        } catch (e: Exception) {
            onError("Camera bind failed: ${e.message}")
        }
    }

    private fun analyze(image: ImageProxy, s: StreamSettings) {
        try {
            if (!running.get()) return
            val server = server ?: return
            val jpeg = encodeJpeg(image, s.quality)
            if (jpeg.isNotEmpty()) server.broadcastFrame(jpeg)
            val now = System.nanoTime()
            val dtSec = (now - lastEncodeTime) / 1e9
            lastEncodeTime = now
            if (dtSec > 0) {
                val inst = 1.0 / dtSec
                encFps = if (encFps == 0.0) inst else encFps * 0.9 + inst * 0.1
            }
        } catch (e: Exception) {
            Log.w(TAG, "Encode error: ${e.message}")
        } finally {
            image.close()
        }
    }

    @Suppress("DEPRECATION")
    private fun encodeJpeg(image: ImageProxy, quality: Int): ByteArray {
        val bmp = image.toBitmap()
        val bos = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, quality, bos)
        if (!bmp.isRecycled) bmp.recycle()
        return bos.toByteArray()
    }

    private fun startServer(s: StreamSettings) {
        stopServer()
        try {
            val ws = WssServer(s.port) { clients ->
                onStatus(s.port, clients, encFps)
            }
            server = ws
            ws.start()
            Log.i(TAG, "WebSocket server started on port ${s.port}")
        } catch (e: Exception) {
            server = null
            onError("Cannot bind WebSocket port ${s.port}: ${e.message}")
        }
    }

    private fun stopServer() {
        val ws = server ?: return
        server = null
        try {
            ws.stop(500)
        } catch (_: Exception) {
        }
        Log.i(TAG, "WebSocket server stopped")
    }

    fun localIp(): String {
        try {
            val ni = NetworkInterface.getNetworkInterfaces().toList()
                .filter { it.isUp && !it.isLoopback }
                .flatMap { it.inetAddresses.toList() }
                .filterIsInstance<Inet4Address>()
                .firstOrNull { !it.isLoopbackAddress }
            return ni?.hostAddress ?: "none"
        } catch (_: Exception) {
            return "none"
        }
    }

    /**
     * Stream frames in the display orientation (landscape for this app) so the
     * desktop receives upright images. With ROTATION_0 the frames would arrive
     * in the raw sensor orientation (portrait on most phones) — sideways faces
     * wreck MediaPipe landmark mapping and produce garbage pose estimates.
     */
    @Suppress("DEPRECATION")
    private fun displayRotation(): Int {
        if (Build.VERSION.SDK_INT >= 30) {
            previewView.display?.rotation?.let { return it }
            return Surface.ROTATION_0
        }
        return (context.getSystemService(Context.WINDOW_SERVICE) as? android.view.WindowManager)
            ?.defaultDisplay?.rotation ?: Surface.ROTATION_0
    }

    private fun acquireWakeLock() {
        try {
            val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "HeadTrackerCam:stream")
                .apply { acquire() }
        } catch (_: Exception) {
        }
    }

    private fun releaseWakeLock() {
        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (_: Exception) {
        }
        wakeLock = null
    }

    companion object {
        private const val TAG = "HeadTrackerCam"
    }
}

/** Lifecycle that stays RESUMED so CameraX keeps running in the background. */
private class AlwaysOnLifecycleOwner : LifecycleOwner {
    private val registry = LifecycleRegistry(this)

    init {
        registry.currentState = Lifecycle.State.RESUMED
    }

    override val lifecycle: Lifecycle get() = registry
}