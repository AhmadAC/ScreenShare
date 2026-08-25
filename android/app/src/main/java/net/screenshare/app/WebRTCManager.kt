package net.screenshare.app

import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjection
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import org.webrtc.*
import java.util.concurrent.ConcurrentHashMap

class WebRTCManager(
    private val context: Context,
    private val screenCaptureIntent: Intent
) {
    private val rootEglBase: EglBase = EglBase.create()
    private val peerConnectionFactory: PeerConnectionFactory
    private var surfaceTextureHelper: SurfaceTextureHelper? = null
    private var screenCapturer: ScreenCapturerAndroid? = null
    private var videoSource: VideoSource? = null
    var localVideoTrack: VideoTrack? = null
        private set

    val peerConnections = ConcurrentHashMap<String, PeerConnection>()

    init {
        val initOptions = PeerConnectionFactory.InitializationOptions.builder(context)
            .setEnableInternalTracer(false)
            .createInitializationOptions()
        PeerConnectionFactory.initialize(initOptions)

        val encoderFactory = DefaultVideoEncoderFactory(
            rootEglBase.eglBaseContext,
            true, // enableIntelVp8Encoder
            true  // enableH264HighProfile
        )
        val decoderFactory = DefaultVideoDecoderFactory(rootEglBase.eglBaseContext)

        peerConnectionFactory = PeerConnectionFactory.builder()
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .setOptions(PeerConnectionFactory.Options())
            .createPeerConnectionFactory()
    }

    fun startScreenCapture(): VideoTrack? {
        screenCapturer = ScreenCapturerAndroid(
            screenCaptureIntent,
            object : MediaProjection.Callback() {
                override fun onStop() {
                    Log.w(TAG, "User revoked MediaProjection permission")
                }
            }
        )

        surfaceTextureHelper = SurfaceTextureHelper.create("ScreenCaptureThread", rootEglBase.eglBaseContext)
        videoSource = peerConnectionFactory.createVideoSource(screenCapturer!!.isScreencast)
        screenCapturer!!.initialize(surfaceTextureHelper, context, videoSource!!.capturerObserver)

        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        wm.defaultDisplay.getRealMetrics(metrics)

        // Capture at native resolution up to 1080p, 60fps for ultra fluid code/screen presentation
        var width = metrics.widthPixels
        var height = metrics.heightPixels
        val maxDim = 1920
        if (width > maxDim || height > maxDim) {
            val scale = maxDim.toFloat() / maxOf(width, height)
            width = (width * scale).toInt()
            height = (height * scale).toInt()
        }

        // Align dimensions to 16 for H.264 / VP8 hardware encoder alignment
        width = width and 15.inv()
        height = height and 15.inv()

        Log.d(TAG, "Starting ScreenCapturer: ${width}x${height}@60fps")
        screenCapturer!!.startCapture(width, height, 60)

        localVideoTrack = peerConnectionFactory.createVideoTrack("SCREEN_SHARE_TRACK_V0", videoSource)
        localVideoTrack?.setEnabled(true)
        return localVideoTrack
    }

    fun createPeerConnectionForSession(
        sid: String,
        iceServersConfig: List<IceServerConfig>,
        onIceCandidate: (IceCandidatePayload) -> Unit,
        onOfferCreated: (SessionDescription) -> Unit
    ): PeerConnection? {
        val iceServers = iceServersConfig.map { cfg ->
            val builder = PeerConnection.IceServer.builder(cfg.urls)
            if (!cfg.username.isNullOrEmpty()) builder.setUsername(cfg.username)
            if (!cfg.credential.isNullOrEmpty()) builder.setPassword(cfg.credential)
            builder.createIceServer()
        }

        val rtcConfig = PeerConnection.RTCConfiguration(iceServers).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
            enableDtlsSrtp = true
        }

        val pc = peerConnectionFactory.createPeerConnection(rtcConfig, object : PeerConnection.Observer {
            override fun onIceCandidate(candidate: IceCandidate) {
                onIceCandidate(
                    IceCandidatePayload(
                        candidate = candidate.sdp,
                        sdpMid = candidate.sdpMid,
                        sdpMLineIndex = candidate.sdpMLineIndex
                    )
                )
            }

            override fun onSignalingChange(state: PeerConnection.SignalingState?) {}
            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState?) {
                Log.d(TAG, "[$sid] IceConnectionState: $state")
            }
            override fun onIceConnectionReceivingChange(receiving: Boolean) {}
            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState?) {}
            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>?) {}
            override fun onAddStream(stream: MediaStream?) {}
            override fun onRemoveStream(stream: MediaStream?) {}
            override fun onDataChannel(dataChannel: DataChannel?) {}
            override fun onRenegotiationNeeded() {}
            override fun onAddTrack(receiver: RtpReceiver?, streams: Array<out MediaStream>?) {}
        })

        if (pc != null && localVideoTrack != null) {
            pc.addTrack(localVideoTrack, listOf("ARDAMS"))

            val constraints = MediaConstraints().apply {
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "true"))
                mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "false"))
            }

            pc.createOffer(object : SdpObserver {
                override fun onCreateSuccess(desc: SessionDescription) {
                    pc.setLocalDescription(object : SdpObserver {
                        override fun onCreateSuccess(p0: SessionDescription?) {}
                        override fun onSetSuccess() {
                            onOfferCreated(desc)
                        }
                        override fun onCreateFailure(err: String?) {}
                        override fun onSetFailure(err: String?) {
                            Log.e(TAG, "[$sid] Failed to set local description: $err")
                        }
                    }, desc)
                }

                override fun onSetSuccess() {}
                override fun onCreateFailure(err: String?) {
                    Log.e(TAG, "[$sid] Failed to create offer: $err")
                }
                override fun onSetFailure(err: String?) {}
            }, constraints)

            peerConnections[sid] = pc
        }

        return pc
    }

    fun setRemoteAnswer(sid: String, sdp: String) {
        val pc = peerConnections[sid] ?: return
        val desc = SessionDescription(SessionDescription.Type.ANSWER, sdp)
        pc.setRemoteDescription(object : SdpObserver {
            override fun onCreateSuccess(p0: SessionDescription?) {}
            override fun onSetSuccess() {
                Log.d(TAG, "[$sid] Remote description successfully applied")
            }
            override fun onCreateFailure(p0: String?) {}
            override fun onSetFailure(err: String?) {
                Log.e(TAG, "[$sid] Failed to set remote description: $err")
            }
        }, desc)
    }

    fun addRemoteIceCandidate(sid: String, candidate: IceCandidatePayload) {
        val pc = peerConnections[sid] ?: return
        val rtcCandidate = IceCandidate(candidate.sdpMid, candidate.sdpMLineIndex, candidate.candidate)
        pc.addIceCandidate(rtcCandidate)
    }

    fun closeSession(sid: String) {
        peerConnections.remove(sid)?.dispose()
    }

    fun stop() {
        try {
            screenCapturer?.stopCapture()
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping screen capturer", e)
        }
        screenCapturer?.dispose()
        screenCapturer = null

        surfaceTextureHelper?.dispose()
        surfaceTextureHelper = null

        videoSource?.dispose()
        videoSource = null

        peerConnections.values.forEach { it.dispose() }
        peerConnections.clear()

        peerConnectionFactory.dispose()
        rootEglBase.release()
    }

    companion object {
        private const val TAG = "WebRTCManager"
    }
}