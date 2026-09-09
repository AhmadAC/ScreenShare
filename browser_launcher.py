import os
import sys
import shutil
import tempfile
import time
import threading
import subprocess
from system_util import log, get_clean_host_env
from process_util import stream_process_logs

def find_browser_executable():
    """Searches for Microsoft Edge, Chrome, or Chromium across host paths, Snaps, and Flatpaks."""
    clean_env = get_clean_host_env()

    if sys.platform.startswith("win"):
        win_candidates = [
            shutil.which("msedge"), shutil.which("chrome"), shutil.which("brave"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Microsoft\\Edge\\Application\\msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Microsoft\\Edge\\Application\\msedge.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Microsoft\\Edge\\Application\\msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "BraveSoftware\\Brave-Browser\\Application\\brave.exe"),
        ]
        for path in win_candidates:
            if path and os.path.isfile(path):
                log(f"Found Windows browser: '{path}'")
                return [path]
        return None

    search_binaries = [
        "microsoft-edge-stable", "microsoft-edge", "msedge", "com.microsoft.Edge",
        "google-chrome-stable", "google-chrome", "chrome", "com.google.Chrome",
        "chromium", "chromium-browser", "org.chromium.Chromium", "brave-browser",
        "brave", "com.brave.Browser", "vivaldi", "vivaldi-stable",
        "microsoft-edge-beta", "microsoft-edge-dev", "google-chrome-beta", "google-chrome-unstable"
    ]

    explicit_dirs = [
        "/usr/bin", "/usr/local/bin", "/bin", "/snap/bin", "/var/lib/flatpak/exports/bin",
        os.path.expanduser("~/.local/share/flatpak/exports/bin"),
        os.path.expanduser("~/.local/bin"), os.path.expanduser("~/bin"),
        "/opt/microsoft/msedge", "/opt/microsoft/msedge-beta", "/opt/microsoft/msedge-dev",
        "/opt/google/chrome", "/opt/brave.com/brave", "/app/bin"
    ]

    log("Scanning host for browser binaries...")
    for binary in search_binaries:
        path = shutil.which(binary, path=clean_env.get("PATH", ""))
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            log(f"Found executable browser in PATH: '{binary}' -> '{path}'")
            return [path]
        
        for d in explicit_dirs:
            full_path = os.path.join(d, binary)
            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                log(f"Found executable browser in '{d}': '{full_path}'")
                return [full_path]

    flatpak_candidates = [
        shutil.which("flatpak", path=clean_env.get("PATH", "")),
        "/usr/bin/flatpak", "/usr/local/bin/flatpak", "/var/lib/flatpak",
    ]
    flatpak_bin = next((f for f in flatpak_candidates if f and os.path.isfile(f) and os.access(f, os.X_OK)), None)
    
    app_ids = [
        "com.microsoft.Edge", "com.microsoft.Edge.Dev", "com.microsoft.Edge.Beta",
        "com.google.Chrome", "com.google.Chrome.Dev", "com.google.Chrome.Beta",
        "org.chromium.Chromium", "com.brave.Browser"
    ]

    if flatpak_bin:
        for app_id in app_ids:
            res = subprocess.run([flatpak_bin, "info", app_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)
            if res.returncode == 0:
                log(f"Found candidate browser in Flatpak: '{app_id}'")
                return [flatpak_bin, "run", app_id]

            flatpak_app_dirs = [
                os.path.join("/var/lib/flatpak/app", app_id),
                os.path.expanduser(f"~/.local/share/flatpak/app/{app_id}"),
            ]
            if any(os.path.isdir(p) for p in flatpak_app_dirs):
                log(f"Found Flatpak app directory for '{app_id}'")
                return [flatpak_bin, "run", app_id]

    return None

def launch_hidden_browser(url):
    """Finds and launches Edge/Chromium on host system with clean, platform-stable flags."""
    executable_cmd = find_browser_executable()

    if not executable_cmd:
        log("========================================================================")
        log("ERROR: No compatible Microsoft Edge or Chromium browser found on system!")
        log(f"Current PATH: {os.environ.get('PATH', '')}")
        log("Please install Microsoft Edge or Google Chrome/Chromium to enable screen sharing.")
        log("========================================================================")
        return None

    isolated_profile_dir = os.path.join(tempfile.gettempdir(), "ScreenShare_browser_profile")
    os.makedirs(isolated_profile_dir, exist_ok=True)

    is_win = sys.platform.startswith("win")

    if is_win:
        cmd = executable_cmd + [
            f"--app={url}",
            f"--user-data-dir={isolated_profile_dir}",
            "--enable-usermedia-screen-capturing",
            "--autoplay-policy=no-user-gesture-required",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-breakpad",
            "--disable-component-update",
            "--window-size=1280,720"
        ]
    else:
        cmd = executable_cmd + [
            f"--app={url}",
            f"--user-data-dir={isolated_profile_dir}",
            "--test-type",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-vulkan",
            "--ozone-platform-hint=auto",
            "--enable-features=WebRTCPipeWireCapturer,VaapiVideoEncoder,VaapiVideoDecoder,CanvasOopRasterization",
            "--disable-features=AudioServiceOutOfProcess,AudioServiceSandbox,IsolateOrigins,site-per-process,Vulkan",
            "--use-fake-ui-for-media-stream",
            "--enable-usermedia-screen-capturing",
            "--auto-select-desktop-capture-source=Entire screen",
            "--autoplay-policy=no-user-gesture-required",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-breakpad",
            "--disable-component-update",
            "--window-size=1280,720"
        ]

    clean_env = get_clean_host_env()
    log("=================================================================")
    log(" Launching Browser Subprocess")
    log(f" Command         : {' '.join(cmd)}")
    log(f" Profile Dir     : {isolated_profile_dir}")
    log(f" DISPLAY         : {clean_env.get('DISPLAY', '<none>')}")
    log(f" WAYLAND_DISPLAY : {clean_env.get('WAYLAND_DISPLAY', '<none>')}")
    log(f" XDG_DATA_DIRS   : {clean_env.get('XDG_DATA_DIRS', '<none>')}")
    log("=================================================================")

    try:
        proc = subprocess.Popen(
            cmd, env=clean_env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1
        )
        stream_process_logs(proc, "Browser")

        def check_browser_health():
            time.sleep(3.0)
            ret = proc.poll()
            if ret is not None:
                log(f"CRITICAL: Browser terminated unexpectedly shortly after launch! Exit code: {ret}")
            else:
                log("Browser process is active and running normally.")

        threading.Thread(target=check_browser_health, daemon=True).start()
        return proc
    except Exception as e:
        log(f"CRITICAL: Failed to spawn browser process: {e}")
        return None