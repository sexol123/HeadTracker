package com.headtracker.cam

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.WindowManager
import android.widget.ArrayAdapter
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.headtracker.cam.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs
    private var controller: StreamController? = null
    private var streaming = false
    private var torchOn = false

    private val permLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) controller?.startCamera() else status("Camera permission denied")
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        prefs = Prefs(this)
        val s = prefs.load()

        controller = StreamController(
            context = this,
            previewView = binding.previewView,
            onStatus = { port, clients, fps -> runOnUiThread { showStatus(port, clients, fps) } },
            onError = { msg -> runOnUiThread { status(msg) } },
        )

        setupSpinners(s)
        binding.editPort.setText(s.port.toString())

        binding.btnStart.setOnClickListener { toggleStream() }
        binding.btnLens.setOnClickListener {
            val back = !currentSettings().backCamera
            binding.btnLens.text = if (back) "Camera: Back" else "Camera: Front"
            controller?.switchLens(back, currentSettings().also { prefs.save(it) })
            updateTorchEnabled()
        }
        binding.btnTorch.setOnClickListener {
            torchOn = !torchOn
            controller?.setTorch(torchOn)
            binding.btnTorch.isSelected = torchOn
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permLauncher.launch(Manifest.permission.CAMERA)
        } else {
            controller?.startCamera()
        }
    }

    override fun onStop() {
        super.onStop()
        // Streaming deliberately keeps running in the background: the camera
        // is bound to an always-on lifecycle and keeps serving the desktop.
    }

    override fun onDestroy() {
        controller?.shutdown()
        super.onDestroy()
    }

    private fun setupSpinners(s: StreamSettings) {
        binding.spinRes.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item,
            listOf("320x240", "640x480", "1280x720"),
        )
        binding.spinRes.setSelection(
            when (s.width to s.height) {
                320 to 240 -> 0
                640 to 480 -> 1
                else -> 2
            },
        )
        binding.spinFps.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item, listOf("15", "30", "60"),
        )
        binding.spinFps.setSelection(listOf(15, 30, 60).indexOf(s.fps).coerceAtLeast(0))
        binding.spinQuality.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item, listOf("50", "70", "85"),
        )
        binding.spinQuality.setSelection(listOf(50, 70, 85).indexOf(s.quality).coerceAtLeast(0))
    }

    private fun currentSettings(): StreamSettings {
        val res = binding.spinRes.selectedItem as String
        val (w, h) = res.split("x").let { it[0].toInt() to it[1].toInt() }
        val port = binding.editPort.text.toString().trim().toIntOrNull() ?: 8080
        return StreamSettings(
            port = port.coerceIn(1024, 65535),
            width = w,
            height = h,
            fps = (binding.spinFps.selectedItem as String).toInt(),
            quality = (binding.spinQuality.selectedItem as String).toInt(),
            backCamera = binding.btnLens.text.toString().startsWith("Camera: Back"),
        )
    }

    private fun toggleStream() {
        val s = currentSettings()
        prefs.save(s)
        streaming = !streaming
        controller?.setStreaming(streaming, s)
        if (streaming) {
            binding.btnStart.text = "Stop stream"
            binding.btnStart.isSelected = true
            showStatus(s.port, 0, 0.0)
        } else {
            binding.btnStart.text = "Start stream"
            binding.btnStart.isSelected = false
            status("Streaming stopped")
        }
        binding.editPort.isEnabled = !streaming
        binding.spinRes.isEnabled = !streaming
        binding.spinFps.isEnabled = !streaming
        binding.spinQuality.isEnabled = !streaming
        binding.btnLens.isEnabled = !streaming
        binding.btnTorch.isEnabled = !streaming
    }

    private fun updateTorchEnabled() {
        val ctl = controller ?: return
        binding.btnTorch.isEnabled = ctl.torchSupported()
        if (!binding.btnTorch.isEnabled) {
            torchOn = false
            binding.btnTorch.isSelected = false
        }
    }

    private fun showStatus(port: Int, clients: Int, fps: Double) {
        val ip = controller?.localIp() ?: "none"
        status(
            "IP: $ip   Port: $port   Clients: $clients\n" +
                "Encoder FPS: ${String.format("%.1f", fps)}\n" +
                "Desktop URL: ws://$ip:$port/ws",
        )
        updateTorchEnabled()
    }

    private fun status(text: String) {
        binding.txtStatus.text = text
    }
}