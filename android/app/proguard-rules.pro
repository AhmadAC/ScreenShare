# WebRTC JNI & Reflection Keep Rules
-keep class org.webrtc.** { *; }
-dontwarn org.webrtc.**

# Gson Models Keep Rules
-keep class net.screenshare.app.** { *; }
-keepclassmembers class net.screenshare.app.** { *; }