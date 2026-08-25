package net.screenshare.app

import android.Manifest
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import net.screenshare.app.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var isSharing = false
    private var detectedWifiIp = "127.0.0.1"

    private val screenCaptureLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startCaptureService(result.data!!)
        } else {
            Toast.makeText(this, "Screen capture permission denied", Toast.LENGTH_SHORT).show()
            updateUI(false, getString(R.string.status_idle))
        }
    }

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        if (permissions[Manifest.permission.POST_NOTIFICATIONS] == true || Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            launchMediaProjectionPrompt()
        }
    }

    private val stateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val state = intent?.getStringExtra(ScreenCaptureService.EXTRA_STATE) ?: return
            val errorMsg = intent.getStringExtra(ScreenCaptureService.EXTRA_ERROR_MSG)

            when (state) {
                ScreenCaptureService.STATE_IDLE -> updateUI(false, getString(R.string.status_idle))
                ScreenCaptureService.STATE_CONNECTING -> updateUI(true, getString(R.string.status_connecting))
                ScreenCaptureService.STATE_BROADCASTING -> updateUI(true, getString(R.string.status_broadcasting))
                ScreenCaptureService.STATE_ERROR -> updateUI(false, "${getString(R.string.status_error)}: ${errorMsg ?: "Unknown"}")
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        refreshWifiIp()

        binding.switchHostOnPhone.setOnCheckedChangeListener { _, isChecked ->
            binding.tilServerUrl.visibility = if (isChecked) View.GONE else View.VISIBLE
            binding.cardViewerInfo.visibility = if (isChecked) View.VISIBLE else View.GONE
            updateViewerUrlText()
        }

        binding.btnCopyLink.setOnClickListener {
            copyViewerLinkToClipboard()
        }

        binding.btnShowQr.setOnClickListener {
            showQrDialog()
        }

        binding.btnToggleShare.setOnClickListener {
            if (isSharing) {
                stopCaptureService()
            } else {
                checkPermissionsAndStart()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshWifiIp()
        val filter = IntentFilter(ScreenCaptureService.BROADCAST_STATE_CHANGE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(stateReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(stateReceiver, filter)
        }
    }

    override fun onPause() {
        super.onPause()
        unregisterReceiver(stateReceiver)
    }

    private fun refreshWifiIp() {
        detectedWifiIp = EmbeddedServerManager.getLocalWifiIp()
        updateViewerUrlText()
    }

    private fun getViewerUrl(): String {
        val roomId = binding.etRoomId.text.toString().trim().ifEmpty { "a" }
        return "http://$detectedWifiIp:5050/?room=$roomId"
    }

    private fun updateViewerUrlText() {
        val url = getViewerUrl()
        binding.tvViewerUrl.text = url
        binding.tvWifiIp.text = "Phone Wi-Fi IP: $detectedWifiIp"
    }

    private fun copyViewerLinkToClipboard() {
        val url = getViewerUrl()
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = ClipData.newPlainText("ScreenShare Viewer URL", url)
        clipboard.setPrimaryClip(clip)
        Toast.makeText(this, "Viewer link copied: $url", Toast.LENGTH_SHORT).show()
    }

    private fun showQrDialog() {
        val url = getViewerUrl()
        val qrBitmap = QRCodeGenerator.generateQrBitmap(url, 600)

        val dialogView = layoutInflater.inflate(R.layout.dialog_qr, null)
        val ivQr = dialogView.findViewById<ImageView>(R.id.ivQrCode)
        val tvUrl = dialogView.findViewById<TextView>(R.id.tvQrUrl)

        ivQr.setImageBitmap(qrBitmap)
        tvUrl.text = url

        AlertDialog.Builder(this)
            .setTitle("Scan to Watch Screen")
            .setView(dialogView)
            .setPositiveButton("Close", null)
            .show()
    }

    private fun checkPermissionsAndStart() {
        val isHostingOnPhone = binding.switchHostOnPhone.isChecked
        val serverUrl = if (isHostingOnPhone) "127.0.0.1:5050" else binding.etServerUrl.text.toString().trim()
        val roomId = binding.etRoomId.text.toString().trim()

        if (serverUrl.isEmpty() || roomId.isEmpty()) {
            Toast.makeText(this, "Please enter a valid Server URL and Room ID", Toast.LENGTH_SHORT).show()
            return
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissionLauncher.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS))
                return
            }
        }
        launchMediaProjectionPrompt()
    }

    private fun launchMediaProjectionPrompt() {
        val projectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        screenCaptureLauncher.launch(projectionManager.createScreenCaptureIntent())
    }

    private fun startCaptureService(resultData: Intent) {
        val isHostingOnPhone = binding.switchHostOnPhone.isChecked
        val serverUrl = if (isHostingOnPhone) "127.0.0.1:5050" else binding.etServerUrl.text.toString().trim()
        val roomId = binding.etRoomId.text.toString().trim()
        val username = binding.etUsername.text.toString().trim()

        val serviceIntent = Intent(this, ScreenCaptureService::class.java).apply {
            putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, resultData)
            putExtra(ScreenCaptureService.EXTRA_SERVER_URL, serverUrl)
            putExtra(ScreenCaptureService.EXTRA_ROOM_ID, roomId)
            putExtra(ScreenCaptureService.EXTRA_USERNAME, username)
            putExtra(ScreenCaptureService.EXTRA_HOST_SERVER, isHostingOnPhone)
            putExtra(ScreenCaptureService.EXTRA_LOCAL_IP, detectedWifiIp)
        }

        ContextCompat.startForegroundService(this, serviceIntent)
        updateUI(true, getString(R.string.status_connecting))
    }

    private fun stopCaptureService() {
        val serviceIntent = Intent(this, ScreenCaptureService::class.java).apply {
            action = ScreenCaptureService.ACTION_STOP
        }
        startService(serviceIntent)
        updateUI(false, getString(R.string.status_idle))
    }

    private fun updateUI(sharing: Boolean, statusText: String) {
        isSharing = sharing
        binding.tvStatus.text = statusText
        binding.btnToggleShare.text = if (sharing) getString(R.string.stop_sharing) else getString(R.string.start_sharing)
        binding.btnToggleShare.setBackgroundColor(
            ContextCompat.getColor(this, if (sharing) R.color.danger else R.color.primary)
        )
        binding.switchHostOnPhone.isEnabled = !sharing
        binding.etServerUrl.isEnabled = !sharing
        binding.etRoomId.isEnabled = !sharing
        binding.etUsername.isEnabled = !sharing
    }
}