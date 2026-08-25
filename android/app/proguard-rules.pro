# =====================================================================
# WebRTC JNI, Native & Reflection Keep Rules
# =====================================================================
-keep class org.webrtc.** { *; }
-dontwarn org.webrtc.**

# Keep native methods and JNI bindings intact
-keepclasseswithmembernames class * {
    native <methods>;
}

# =====================================================================
# Gson & Application Data Models Keep Rules
# =====================================================================
# Retain custom data transfer models and serialized fields
-keep class net.screenshare.app.** { *; }
-keepclassmembers class net.screenshare.app.** { *; }

# Retain Gson annotations and classes referenced during JSON parsing
-keepattributes Signature
-keepattributes *Annotation*
-dontwarn sun.misc.**
-keep class com.google.gson.** { *; }
-keep class * implements com.google.gson.TypeAdapter
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer

# Prevent obfuscation of fields with @SerializedName
-keepclassmembers class * {
    @com.google.gson.annotations.SerializedName <fields>;
}

# =====================================================================
# OkHttp & WebSocket Keep Rules
# =====================================================================
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**
-dontwarn org.conscrypt.**
-keepnames class okhttp3.internal.publicsuffix.PublicSuffixDatabase
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }

# =====================================================================
# Kotlin Coroutines & AndroidX Keep Rules
# =====================================================================
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}
-dontwarn kotlinx.coroutines.**