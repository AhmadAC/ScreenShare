package net.screenshare.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlin.concurrent.thread

class ScreenCaptureService : Service(), SignalingClient.Listener {

    private var rtcManager: WebRTCManager? = null
    private var signalingClient: SignalingClient? = null
    private var serverUrl: String = ""
    private var roomId: String = ""
    private var username: String = ""
    private var isHostServer: Boolean = false
    private var localIp: String = "127.0.0.1"

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null) return START_NOT_STICKY

        val action = intent.action
        if (action == ACTION_STOP) {
            stopScreenSharing()
            stopSelf()
            return START_NOT_STICKY
        }

        serverUrl = intent.getStringExtra(EXTRA_SERVER_URL) ?: "127.0.0.1:5050"
        roomId = intent.getStringExtra(EXTRA_ROOM_ID) ?: "a"
        username = intent.getStringExtra(EXTRA_USERNAME) ?: "Android Host"
        isHostServer = intent.getBooleanExtra(EXTRA_HOST_SERVER, false)
        localIp = intent.getStringExtra(EXTRA_LOCAL_IP) ?: "127.0.0.1"

        val captureIntentData: Intent? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(EXTRA_RESULT_DATA) as? Intent
        }

        if (captureIntentData == null) {
            Log.e(TAG, "Screen capture Intent is null")
            stopSelf()
            return START_NOT_STICKY
        }

        createNotificationChannel()
        val notification = createNotification()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
                )
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        broadcastState(STATE_CONNECTING)

        thread(name = "ScreenCaptureStartup", isDaemon = true) {
            if (isHostServer) {
                Log.i(TAG, "Starting embedded server on $localIp:5050...")
                EmbeddedServerManager.startServer(applicationContext, localIp)
            }

            rtcManager = WebRTCManager(applicationContext, captureIntentData)
            rtcManager?.startScreenCapture()

            val targetSignalingUrl = if (isHostServer) "127.0.0.1:5050" else serverUrl
            signalingClient = SignalingClient(targetSignalingUrl, this)
            signalingClient?.connect()
        }

        return START_STICKY
    }

    private fun createNotification(): Notification {
        val stopIntent = Intent(this, ScreenCaptureService::class.java).apply {
            action = ACTION_STOP
        }

        val stopPendingIntent = PendingIntent.getService(
            this,
            0,
            stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val viewerText = if (isHostServer) "Viewers: http://$localIp:5050/?room=$roomId" else getString(R.string.notification_text)

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(viewerText)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .addAction(android.R.drawable.ic_delete, "Stop Sharing", stopPendingIntent)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel_name),
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    // --- Signaling Callbacks ---

    override fun onConnected() {
        signalingClient?.sendCreateRoom(roomId, username)
    }

    override fun onRoomJoined() {
        broadcastState(STATE_BROADCASTING)
        signalingClient?.sendStartShare()
    }

    override fun onHostSessionReceived(session: HostSessionPayload) {
        rtcManager?.createPeerConnectionForSession(
            sid = session.id,
            iceServersConfig = session.iceServers,
            onIceCandidate = { candidate ->
                signalingClient?.sendHostIceCandidate(session.id, candidate)
            },
            onOfferCreated = { desc ->
                signalingClient?.sendHostOffer(session.id, desc.description)
            }
        )
    }

    override fun onClientAnswerReceived(sid: String, sdp: String) {
        rtcManager?.setRemoteAnswer(sid, sdp)
    }

    override fun onClientIceCandidateReceived(sid: String, candidate: IceCandidatePayload) {
        rtcManager?.addRemoteIceCandidate(sid, candidate)
    }

    override fun onEndShare(sid: String) {
        rtcManager?.closeSession(sid)
    }

    override fun onError(error: String) {
        broadcastState(STATE_ERROR, error)
    }

    override fun onDisconnected() {
        broadcastState(STATE_IDLE)
    }

    private fun stopScreenSharing() {
        signalingClient?.sendStopShare()
        signalingClient?.disconnect()
        signalingClient = null

        rtcManager?.stop()
        rtcManager = null

        if (isHostServer) {
            EmbeddedServerManager.stopServer()
        }

        broadcastState(STATE_IDLE)
    }

    private fun broadcastState(state: String, errorMsg: String? = null) {
        val intent = Intent(BROADCAST_STATE_CHANGE).apply {
            putExtra(EXTRA_STATE, state)
            if (errorMsg != null) putExtra(EXTRA_ERROR_MSG, errorMsg)
            setPackage(packageName)
        }
        sendBroadcast(intent)
    }

    override fun onDestroy() {
        stopScreenSharing()
        super.onDestroy()
    }

    companion object {
        const val TAG = "ScreenCaptureService"
        const val CHANNEL_ID = "screenshare_channel"
        const val NOTIFICATION_ID = 1001

        const val ACTION_STOP = "net.screenshare.app.ACTION_STOP"
        const val EXTRA_RESULT_DATA = "EXTRA_RESULT_DATA"
        const val EXTRA_SERVER_URL = "EXTRA_SERVER_URL"
        const val EXTRA_ROOM_ID = "EXTRA_ROOM_ID"
        const val EXTRA_USERNAME = "EXTRA_USERNAME"
        const val EXTRA_HOST_SERVER = "EXTRA_HOST_SERVER"
        const val EXTRA_LOCAL_IP = "EXTRA_LOCAL_IP"

        const val BROADCAST_STATE_CHANGE = "net.screenshare.app.STATE_CHANGE"
        const val EXTRA_STATE = "EXTRA_STATE"
        const val EXTRA_ERROR_MSG = "EXTRA_ERROR_MSG"

        const val STATE_IDLE = "STATE_IDLE"
        const val STATE_CONNECTING = "STATE_CONNECTING"
        const val STATE_BROADCASTING = "STATE_BROADCASTING"
        const val STATE_ERROR = "STATE_ERROR"
    }
}