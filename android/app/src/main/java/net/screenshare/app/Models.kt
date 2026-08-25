package net.screenshare.app

import com.google.gson.JsonElement
import com.google.gson.annotations.SerializedName

data class SignalingMessage(
    @SerializedName("type") val type: String,
    @SerializedName("payload") val payload: JsonElement
)

data class CreateRoomPayload(
    @SerializedName("id") val id: String,
    @SerializedName("mode") val mode: String = "stun",
    @SerializedName("closeOnOwnerLeave") val closeOnOwnerLeave: Boolean = false,
    @SerializedName("username") val username: String,
    @SerializedName("joinIfExist") val joinIfExist: Boolean = true
)

data class HostSessionPayload(
    @SerializedName("id") val id: String,
    @SerializedName("peer") val peer: String,
    @SerializedName("iceServers") val iceServers: List<IceServerConfig>
)

data class IceServerConfig(
    @SerializedName("urls") val urls: List<String>,
    @SerializedName("username") val username: String? = null,
    @SerializedName("credential") val credential: String? = null
)

data class P2PMessage<T>(
    @SerializedName("sid") val sid: String,
    @SerializedName("value") val value: T
)

data class SdpDescription(
    @SerializedName("type") val type: String,
    @SerializedName("sdp") val sdp: String
)

data class IceCandidatePayload(
    @SerializedName("candidate") val candidate: String,
    @SerializedName("sdpMid") val sdpMid: String?,
    @SerializedName("sdpMLineIndex") val sdpMLineIndex: Int
)