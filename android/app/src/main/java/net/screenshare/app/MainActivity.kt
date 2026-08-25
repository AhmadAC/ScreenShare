package net.screenshare.app

import android.Manifest
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import net.screenshare.app.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var isSharing = false

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

    private fun checkPermissionsAndStart() {
        val serverUrl = binding.etServerUrl.text.toString().trim()
        val roomId = binding.etRoomId.text.toString().trim()
        if (serverUrl.isEmpty() || roomId.isEmpty()) {
            Toast.makeText(this, "Please fill in Server URL and Room ID", Toast.LENGTH_SHORT).show()
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
        val serviceIntent = Intent(this, ScreenCaptureService::class.java)
        serviceIntent.putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, resultData)
        serviceIntent.putExtra(ScreenCaptureService.EXTRA_SERVER_URL, binding.etServerUrl.text.toString().trim())
        serviceIntent.putExtra(ScreenCaptureService.EXTRA_ROOM_ID, binding.etRoomId.text.toString().trim())
        serviceIntent.putExtra(ScreenCaptureService.EXTRA_USERNAME, binding.etUsername.text.toString().trim())

        ContextCompat.startForegroundService(this, serviceIntent)
        updateUI(true, getString(R.string.status_connecting))
    }

    private fun stopCaptureService() {
        val serviceIntent = Intent(this, ScreenCaptureService::class.java)
        serviceIntent.action = ScreenCaptureService.ACTION_STOP
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
        binding.etServerUrl.isEnabled = !sharing
        binding.etRoomId.isEnabled = !sharing
        binding.etUsername.isEnabled = !sharing
    }
}