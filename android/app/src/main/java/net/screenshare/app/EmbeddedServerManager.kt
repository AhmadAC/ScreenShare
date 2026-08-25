package net.screenshare.app

import android.content.Context
import android.os.Build
import android.util.Log
import java.io.BufferedReader
import java.io.File
import java.io.FileOutputStream
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.NetworkInterface
import java.net.URL
import java.util.Collections
import kotlin.concurrent.thread

object EmbeddedServerManager {

    private const val TAG = "EmbeddedServerManager"
    private var serverProcess: Process? = null
    private var isRunning = false

    fun getLocalWifiIp(): String {
        try {
            val interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
            val candidateIps = mutableListOf<Pair<String, String>>()

            for (networkInterface in interfaces) {
                if (networkInterface.isLoopback || !networkInterface.isUp) continue
                val name = networkInterface.name.lowercase()

                val addresses = Collections.list(networkInterface.inetAddresses)
                for (addr in addresses) {
                    if (!addr.isLoopbackAddress && addr.hostAddress != null) {
                        val ip = addr.hostAddress!!
                        if (!ip.contains(":") && !ip.startsWith("127.") && !ip.startsWith("169.254.")) {
                            candidateIps.add(Pair(name, ip))
                        }
                    }
                }
            }

            for ((name, ip) in candidateIps) {
                if (name.startsWith("wlan") || name.startsWith("eth") || name.startsWith("ap") || name.startsWith("wifi")) {
                    return ip
                }
            }

            if (candidateIps.isNotEmpty()) {
                return candidateIps[0].second
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error detecting Wi-Fi IP", e)
        }
        return "127.0.0.1"
    }

    @Synchronized
    fun startServer(context: Context, localIp: String): Boolean {
        if (isRunning && serverProcess?.isAlive == true) {
            Log.i(TAG, "Embedded ScreenShare server is already running.")
            return true
        }

        val binaryPath = resolveOrExtractBinary(context)
        if (binaryPath == null) {
            Log.e(TAG, "Could not resolve ScreenShare binary for execution.")
            return false
        }

        try {
            val workingDir = context.filesDir
            val processBuilder = ProcessBuilder(binaryPath, "serve")
            processBuilder.directory(workingDir)

            val env = processBuilder.environment()
            env["SCREENSHARE_EXTERNAL_IP"] = localIp
            env["SCREENSHARE_SERVER_ADDRESS"] = "0.0.0.0:5050"
            env["SCREENSHARE_TURN_ADDRESS"] = "0.0.0.0:3478"
            env["SCREENSHARE_AUTH_MODE"] = "none"
            env["SCREENSHARE_CLOSE_ROOM_WHEN_OWNER_LEAVES"] = "false"
            env["SCREENSHARE_LOG_LEVEL"] = "info"

            val usersFile = File(workingDir, "users")
            if (!usersFile.exists()) {
                try {
                    usersFile.writeText("# ScreenShare users file\n")
                } catch (_: Exception) {}
            }
            env["SCREENSHARE_USERS_FILE"] = usersFile.absolutePath

            Log.i(TAG, "Spawning embedded server process from $binaryPath with IP $localIp")
            val process = processBuilder.start()
            serverProcess = process
            isRunning = true

            thread(name = "ServerStdoutThread", isDaemon = true) {
                try {
                    val reader = BufferedReader(InputStreamReader(process.inputStream))
                    var line: String?
                    while (reader.readLine().also { line = it } != null) {
                        Log.i(TAG, "[Server] $line")
                    }
                } catch (_: Exception) {}
            }

            thread(name = "ServerStderrThread", isDaemon = true) {
                try {
                    val reader = BufferedReader(InputStreamReader(process.errorStream))
                    var line: String?
                    while (reader.readLine().also { line = it } != null) {
                        Log.e(TAG, "[Server Err] $line")
                    }
                } catch (_: Exception) {}
            }

            val isHealthy = waitForServerHealth("http://127.0.0.1:5050/health", timeoutMs = 5000)
            if (!isHealthy) {
                Log.w(TAG, "Server did not answer /health in time, but process is running.")
            }
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start embedded server process", e)
            stopServer()
            return false
        }
    }

    @Synchronized
    fun stopServer() {
        try {
            serverProcess?.destroy()
            serverProcess = null
            isRunning = false
            Log.i(TAG, "Embedded ScreenShare server stopped.")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping embedded server", e)
        }
    }

    private fun resolveOrExtractBinary(context: Context): String? {
        val nativeDir = File(context.applicationInfo.nativeLibraryDir)
        val candidateNames = listOf("libscreenshare_server.so", "libScreenShare.so", "ScreenShare")

        for (name in candidateNames) {
            val nativeFile = File(nativeDir, name)
            if (nativeFile.exists() && nativeFile.canExecute()) {
                Log.i(TAG, "Found executable native binary in nativeLibraryDir: ${nativeFile.absolutePath}")
                return nativeFile.absolutePath
            }
        }

        val destinationFile = File(context.filesDir, "ScreenShare-server")
        if (!destinationFile.exists() || destinationFile.length() == 0L) {
            val assetNames = listOf(
                "ScreenShare-server",
                "ScreenShare-${getPrimaryAbi()}",
                "libscreenshare_server.so"
            )

            var extracted = false
            for (asset in assetNames) {
                try {
                    context.assets.open(asset).use { input ->
                        FileOutputStream(destinationFile).use { output ->
                            input.copyTo(output)
                        }
                    }
                    extracted = true
                    Log.i(TAG, "Extracted binary from assets/$asset to ${destinationFile.absolutePath}")
                    break
                } catch (_: Exception) {}
            }

            if (!extracted) {
                Log.w(TAG, "No pre-bundled server binary found in assets or nativeLibraryDir.")
            }
        }

        if (destinationFile.exists()) {
            destinationFile.setExecutable(true, false)
            return destinationFile.absolutePath
        }

        return null
    }

    private fun getPrimaryAbi(): String {
        return if (Build.SUPPORTED_ABIS.isNotEmpty()) {
            Build.SUPPORTED_ABIS[0]
        } else {
            "arm64-v8a"
        }
    }

    private fun waitForServerHealth(healthUrl: String, timeoutMs: Long): Boolean {
        val startTime = System.currentTimeMillis()
        while (System.currentTimeMillis() - startTime < timeoutMs) {
            try {
                val url = URL(healthUrl)
                val conn = url.openConnection() as HttpURLConnection
                conn.connectTimeout = 500
                conn.readTimeout = 500
                conn.requestMethod = "GET"
                val code = conn.responseCode
                conn.disconnect()
                if (code == 200) {
                    Log.i(TAG, "Embedded server is online and healthy.")
                    return true
                }
            } catch (_: Exception) {
                Thread.sleep(200)
            }
        }
        return false
    }
}