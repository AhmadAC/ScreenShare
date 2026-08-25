package net.screenshare.app

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

class SignalingClient(
    private val serverUrl: String,
    private val listener: Listener
) {
    interface Listener {
        fun onConnected()
        fun onRoomJoined()
        fun onHostSessionReceived(session: HostSessionPayload)
        fun onClientAnswerReceived(sid: String, sdp: String)
        fun onClientIceCandidateReceived(sid: String, candidate: IceCandidatePayload)
        fun onEndShare(sid: String)
        fun onError(error: String)
        fun onDisconnected()
    }

    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .readTimeout(30, TimeUnit.SECONDS)
        .pingInterval(10, TimeUnit.SECONDS)
        .build()
    private var webSocket: WebSocket? = null

    fun connect() {
        val wsUrl = when {
            serverUrl.startsWith("ws://") || serverUrl.startsWith("wss://") -> {
                if (serverUrl.endsWith("/stream")) serverUrl else "$serverUrl/stream"
            }
            serverUrl.startsWith("http://") -> {
                val base = serverUrl.removePrefix("http://").trimEnd('/')
                "ws://$base/stream"
            }
            serverUrl.startsWith("https://") -> {
                val base = serverUrl.removePrefix("https://").trimEnd('/')
                "wss://$base/stream"
            }
            else -> "ws://${serverUrl.trimEnd('/')}/stream"
        }

        Log.d(TAG, "Connecting to WebSocket: $wsUrl")
        val request = Request.Builder().url(wsUrl).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "WebSocket Connected")
                listener.onConnected()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "WebSocket Rx: $text")
                handleMessage(text)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket Failure: ${t.message}", t)
                listener.onError(t.message ?: "Connection error")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket Closed: code=$code, reason=$reason")
                listener.onDisconnected()
            }
        })
    }

    private fun handleMessage(text: String) {
        try {
            val base = gson.fromJson(text, SignalingMessage::class.java)
            when (base.type) {
                "room" -> {
                    listener.onRoomJoined()
                }
                "hostsession" -> {
                    val session = gson.fromJson(base.payload, HostSessionPayload::class.java)
                    listener.onHostSessionReceived(session)
                }
                "clientanswer" -> {
                    val p2p = base.payload.asJsonObject
                    val sid = p2p.get("sid").asString
                    val value = p2p.get("value").asJsonObject
                    val sdp = value.get("sdp").asString
                    listener.onClientAnswerReceived(sid, sdp)
                }
                "clientice" -> {
                    val p2p = base.payload.asJsonObject
                    val sid = p2p.get("sid").asString
                    val value = gson.fromJson(p2p.get("value"), IceCandidatePayload::class.java)
                    listener.onClientIceCandidateReceived(sid, value)
                }
                "endshare" -> {
                    val sid = base.payload.asString
                    listener.onEndShare(sid)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error handling message", e)
        }
    }

    fun sendCreateRoom(roomId: String, username: String) {
        val payload = CreateRoomPayload(id = roomId, username = username)
        send("create", gson.toJsonTree(payload))
    }

    fun sendStartShare() {
        send("share", JsonObject())
    }

    fun sendStopShare() {
        send("stopshare", JsonObject())
    }

    fun sendHostOffer(sid: String, sdp: String) {
        val offerDesc = SdpDescription(type = "offer", sdp = sdp)
        val payload = P2PMessage(sid = sid, value = offerDesc)
        send("hostoffer", gson.toJsonTree(payload))
    }

    fun sendHostIceCandidate(sid: String, candidate: IceCandidatePayload) {
        val payload = P2PMessage(sid = sid, value = candidate)
        send("hostice", gson.toJsonTree(payload))
    }

    private fun send(type: String, payload: com.google.gson.JsonElement) {
        val msg = SignalingMessage(type = type, payload = payload)
        val json = gson.toJson(msg)
        Log.d(TAG, "WebSocket Tx: $json")
        webSocket?.send(json)
    }

    fun disconnect() {
        webSocket?.close(1000, "User initiated disconnect")
        webSocket = null
    }

    companion object {
        private const val TAG = "SignalingClient"
    }
}