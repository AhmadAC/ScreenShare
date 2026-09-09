import os
import sys
import time
import shutil
import tempfile
import threading
import subprocess
import urllib.request
from system_util import log, BASE_DIR, get_clean_host_env

class ConsoleProgressBar:
    def __init__(self, task="Processing"):
        self.current_step = 0
        self.task = task
        self.detail = ""
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.start_time = time.time()

    def update(self, percent, task=None, detail=""):
        self.current_step = max(0, min(100, percent))
        if task:
            self.task = task
        self.detail = detail
        self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_chars)
        spinner = self.spinner_chars[self.spinner_idx]

        bar_len = 24
        filled_len = int(bar_len * (self.current_step / 100.0))
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed)}s"

        det = f" | {self.detail}" if self.detail else ""
        if len(det) > 36:
            det = det[:33] + "..."

        line = f"\r{spinner} [{bar}] {self.current_step:3d}% ({elapsed_str}) {self.task}{det}"
        sys.stdout.write(line.ljust(85))
        sys.stdout.flush()

    def finish(self, message="Complete!"):
        bar = "█" * 24
        elapsed = time.time() - self.start_time
        line = f"\r✔ [{bar}] 100% ({int(elapsed)}s) {message}"
        sys.stdout.write(line.ljust(85) + "\n")
        sys.stdout.flush()

def needs_rebuild(src_dir, out_bin):
    """Smart rebuild checker. Checks if ui/build, ui/src, or .go files are newer than the built binary."""
    if not os.path.isfile(out_bin):
        return True
    
    ui_build_index = os.path.join(src_dir, "ui", "build", "index.html")
    if not os.path.isfile(ui_build_index):
        return True

    ui_favicon = os.path.join(src_dir, "ui", "build", "favicon.ico")
    if not os.path.isfile(ui_favicon):
        return True

    bin_mtime = os.path.getmtime(out_bin)
    ui_src = os.path.join(src_dir, "ui", "src")
    
    if os.path.isdir(ui_src):
        for root, _, files in os.walk(ui_src):
            for f in files:
                if os.path.getmtime(os.path.join(root, f)) > bin_mtime:
                    return True
                    
    for root, dirs, files in os.walk(src_dir):
        if "ui" in dirs: 
            dirs.remove("ui")
        for f in files:
            if f.endswith(".go") and os.path.getmtime(os.path.join(root, f)) > bin_mtime:
                return True
                
    return False

def build_frontend_ui(src_dir, deno_cmd, pbar=None):
    """Builds the React frontend and guarantees ui/build contains index.html & icons for Go embed."""
    ui_dir = os.path.join(src_dir, "ui")
    ui_build_dir = os.path.join(ui_dir, "build")
    ui_index = os.path.join(ui_build_dir, "index.html")
    ui_public_dir = os.path.join(ui_dir, "public")

    if not os.path.isdir(ui_dir):
        return True

    log("Building React frontend...")
    if pbar:
        pbar.update(10, task="Building UI", detail="Installing Deno packages...")

    if deno_cmd:
        try:
            subprocess.run([deno_cmd, "install"], cwd=ui_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        except Exception as e:
            log(f"Deno install notice: {e}")

    if pbar:
        pbar.update(25, task="Building UI", detail="Running Vite bundler...")

    build_success = False

    # 1. Deno task build (runs "vite build" via package.json)
    if deno_cmd:
        try:
            res = subprocess.run([deno_cmd, "task", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and os.path.isfile(ui_index):
                build_success = True
                log("Frontend UI built successfully with Deno task.")
            else:
                log(f"Deno task build notice: {res.stderr or res.stdout}")
        except Exception as e:
            log(f"Deno task build notice: {e}")

    # 2. Direct Deno vite invocation
    if not build_success and deno_cmd:
        try:
            res = subprocess.run([deno_cmd, "run", "-A", "npm:vite", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and os.path.isfile(ui_index):
                build_success = True
                log("Frontend UI built successfully with Deno Vite.")
            else:
                log(f"Deno direct vite notice: {res.stderr or res.stdout}")
        except Exception as e:
            log(f"Deno direct vite notice: {e}")

    # 3. Node / NPX fallback
    if not build_success:
        npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
        if npx_cmd:
            if pbar:
                pbar.update(35, task="Building UI", detail="Trying npx vite...")
            try:
                res = subprocess.run([npx_cmd, "--yes", "vite", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
                if res.returncode == 0 and os.path.isfile(ui_index):
                    build_success = True
                    log("Frontend UI built successfully with npx vite.")
            except Exception as e:
                log(f"npx vite notice: {e}")

    os.makedirs(ui_build_dir, exist_ok=True)

    # Ensure all static assets from public/ exist in build/
    if os.path.isdir(ui_public_dir):
        for item in os.listdir(ui_public_dir):
            s = os.path.join(ui_public_dir, item)
            d = os.path.join(ui_build_dir, item)
            if os.path.isfile(s) and not os.path.exists(d):
                try:
                    shutil.copy2(s, d)
                except Exception:
                    pass

    # Ensure index.html exists
    if not os.path.isfile(ui_index):
        log("Notice: Populating fallback ui/build/index.html to ensure Go build succeeds...")
        src_index = os.path.join(ui_dir, "index.html")
        if os.path.isfile(src_index):
            shutil.copy2(src_index, ui_index)
        else:
            with open(ui_index, "w", encoding="utf-8") as f:
                f.write("<!DOCTYPE html><html><head><title>ScreenShare</title></head><body><h1>ScreenShare</h1></body></html>")

    return True

def compile_go_binary(src_dir, out_bin, go_cmd, is_win, pbar=None):
    """Compiles the Go binary while streaming downloads and compilation in real-time."""
    log(f"Compiling Go binary using: {go_cmd} ...")
    if pbar:
        pbar.update(45, task="Compiling Server", detail="Initializing Go compiler...")

    if os.path.isfile(out_bin):
        try:
            os.remove(out_bin)
        except Exception:
            pass

    env = os.environ.copy()
    env["CGO_ENABLED"] = "0"
    go_bin_dir = os.path.dirname(go_cmd)
    env["PATH"] = go_bin_dir + os.pathsep + env.get("PATH", "")

    cmd = [go_cmd, "build", "-v", "-ldflags=-s -w -X main.mode=prod", "-o", out_bin, "."]

    pct = 48
    output_lines = []
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=src_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in iter(proc.stdout.readline, ''):
            if not line:
                continue
            clean_line = line.strip()
            output_lines.append(clean_line)

            detail = ""
            if "downloading" in clean_line:
                parts = clean_line.split()
                detail = parts[1] if len(parts) > 1 else clean_line
                if "/" in detail:
                    detail = detail.split("/")[-1]
                detail = f"Downloading {detail}"
                pct = min(82, pct + 1)
            elif clean_line.startswith("github.com/") or clean_line.startswith("golang.org/"):
                pkg_name = clean_line.split("/")[-1]
                detail = f"Compiling {pkg_name}"
                pct = min(96, pct + 1)
            else:
                detail = clean_line[:30]

            if pbar:
                pbar.update(pct, task="Compiling Server", detail=detail)

        proc.wait()

        if proc.returncode == 0 and os.path.isfile(out_bin):
            if not is_win:
                try:
                    os.chmod(out_bin, 0o755)
                except Exception:
                    pass
            if pbar:
                pbar.finish("ScreenShare server compiled successfully!")
            log("Server binary compilation successful.")
            return True
        else:
            if pbar:
                sys.stdout.write("\n")
            err_summary = "\n".join(output_lines[-25:]) if output_lines else "Unknown error"
            log(f"Go build failed with code {proc.returncode}:\n{err_summary}")
            return False
    except Exception as e:
        log(f"Failed to execute Go build: {e}")
        return False

def find_or_build_binary():
    """Locates ScreenShare binary across search directories or auto-builds it."""
    search_dirs = [
        os.path.join(BASE_DIR, "server"),
        BASE_DIR,
        os.path.join(os.getcwd(), "server"),
        os.getcwd(),
        os.path.join(os.path.dirname(BASE_DIR), "server"),
        os.path.dirname(BASE_DIR)
    ]

    is_win = sys.platform.startswith("win")
    target_names = ["ScreenShare.exe", "screenshare.exe"] if is_win else ["ScreenShare", "screenshare"]

    src_dir = None
    for d in search_dirs:
        if os.path.isfile(os.path.join(d, "main.go")):
            src_dir = d
            break

    if src_dir:
        bin_filename = "ScreenShare.exe" if is_win else "ScreenShare"
        out_bin = os.path.join(src_dir, bin_filename)
        if needs_rebuild(src_dir, out_bin):
            log("========================================")
            log("Source files modified or binary missing. Starting compilation...")
            log("========================================")
            
            pbar = ConsoleProgressBar(task="Resolving environment...")
            pbar.update(5, detail="Checking compilers...")

            deno_bins = [
                shutil.which("deno"),
                shutil.which("deno.exe"),
                os.path.join(os.environ.get("USERPROFILE", ""), ".deno", "bin", "deno.exe"),
                os.path.join(os.environ.get("LocalAppData", ""), "deno", "deno.exe"),
                os.path.expanduser("~/.deno/bin/deno"),
                os.path.expanduser("~/.local/bin/deno")
            ]
            deno_cmd = next((d for d in deno_bins if d and os.path.isfile(d)), None)

            go_bins = [
                shutil.which("go"),
                shutil.which("go.exe"),
                os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Go", "bin", "go.exe"),
                os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Go", "bin", "go.exe"),
                os.path.join(os.environ.get("LocalAppData", ""), "Programs", "Go", "bin", "go.exe"),
                "C:\\Go\\bin\\go.exe",
                os.path.join(os.environ.get("USERPROFILE", ""), "go", "bin", "go.exe"),
                os.path.expanduser("~/.local/go/bin/go"),
                os.path.expanduser("~/go/bin/go"),
                "/usr/local/go/bin/go",
                "/usr/bin/go"
            ]
            go_cmd = next((g for g in go_bins if g and os.path.isfile(g)), None)

            build_frontend_ui(src_dir, deno_cmd, pbar)

            if go_cmd:
                compile_success = compile_go_binary(src_dir, out_bin, go_cmd, is_win, pbar)
                if compile_success:
                    return out_bin
            else:
                sys.stdout.write("\n")
                log("Warning: 'go' compiler was not found on your system.")
                if is_win:
                    log("Please install Go on Windows 11 by running in PowerShell: winget install GoLang.Go")
                else:
                    log("Please install Go to compile the server binary.")

    for d in search_dirs:
        for name in target_names:
            bin_path = os.path.join(d, name)
            if os.path.isfile(bin_path):
                if not is_win and not os.access(bin_path, os.X_OK):
                    try:
                        os.chmod(bin_path, 0o755)
                    except Exception:
                        pass
                return bin_path

    for name in target_names:
        in_path = shutil.which(name)
        if in_path:
            return in_path

    return None

def stream_process_logs(proc, prefix_label):
    """Continuously reads stdout and stderr lines from a subprocess and writes them to the log."""
    def read_stream(stream, stream_name):
        try:
            for line in iter(stream.readline, ''):
                if line:
                    log(f"[{prefix_label} {stream_name}] {line.strip()}")
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    if proc.stdout:
        threading.Thread(target=read_stream, args=(proc.stdout, "stdout"), daemon=True).start()
    if proc.stderr:
        threading.Thread(target=read_stream, args=(proc.stderr, "stderr"), daemon=True).start()

def start_screenshare_server(lan_ip):
    """Spawns the Go backend binary, enabling TURN relay and persistent rooms."""
    server_bin = find_or_build_binary()

    if not server_bin or not os.path.isfile(server_bin):
        is_win = sys.platform.startswith("win")
        expected_bin = "ScreenShare.exe" if is_win else "ScreenShare"
        log("========================================")
        log(f"Error: Server executable binary '{expected_bin}' not found.")
        if is_win:
            log("The Go compiler is required to build ScreenShare.exe.")
            log("To install Go on Windows 11, open PowerShell and run:")
            log("  winget install GoLang.Go")
            log("After installation completes, restart PowerShell and re-run this script.")
        else:
            log("Please install Go and build it once by running: go build -o ScreenShare .")
        log("========================================")
        sys.exit(1)

    bin_dir = os.path.dirname(os.path.abspath(server_bin))
    log(f"Using server binary: {server_bin}")
    log(f"Working Directory  : {bin_dir}")

    env = os.environ.copy()
    configs = {
        "EXTERNAL_IP": lan_ip,
        "SERVER_ADDRESS": "0.0.0.0:5050",
        "TURN_ADDRESS": "0.0.0.0:3478",
        "AUTH_MODE": "none",
        "CLOSE_ROOM_WHEN_OWNER_LEAVES": "false",
        "LOG_LEVEL": "info",
    }
    for k, v in configs.items():
        env[f"SCREENSHARE_{k}"] = v
    
    users_candidates = [
        os.path.join(bin_dir, "users"),
        os.path.join(BASE_DIR, "users"),
        os.path.join(BASE_DIR, "server", "users"),
        os.path.join(os.getcwd(), "users"),
        os.path.join(os.getcwd(), "server", "users")
    ]
    for u_path in users_candidates:
        if os.path.isfile(u_path):
            abs_u = os.path.abspath(u_path)
            env["SCREENSHARE_USERS_FILE"] = abs_u
            break

    proc = subprocess.Popen(
        [server_bin, "serve"],
        env=env,
        cwd=bin_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    stream_process_logs(proc, "Server")
    return proc

def wait_for_server(url, proc=None, timeout=6.0):
    """Waits until the local HTTP server is responsive before opening browser."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if proc and proc.poll() is not None:
            log(f"CRITICAL: Backend server terminated prematurely with exit code: {proc.poll()}")
            return False
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status in (200, 302, 304):
                    log(f"Backend server is up and responsive at {url}")
                    return True
        except Exception:
            time.sleep(0.2)
    log(f"Warning: Backend server did not respond at {url} within {timeout} seconds.")
    return False

def find_browser_executable():
    """Searches for Microsoft Edge, Chrome, or Chromium across host paths, Snaps, and Flatpaks."""
    clean_env = get_clean_host_env()

    if sys.platform.startswith("win"):
        win_candidates = [
            shutil.which("msedge"),
            shutil.which("chrome"),
            shutil.which("brave"),
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
    """Finds and launches Edge/Chromium on host system in an isolated profile."""
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

    cmd = executable_cmd + [
        f"--app={url}",
        f"--user-data-dir={isolated_profile_dir}",
        "--test-type",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-vulkan",
        "--disable-application-cache",
        "--disk-cache-size=1",
        "--media-cache-size=1",
        "--ozone-platform-hint=auto",
        "--enable-features=WebRTCPipeWireCapturer,VaapiVideoEncoder,VaapiVideoDecoder,CanvasOopRasterization",
        "--disable-features=AudioServiceOutOfProcess,AudioServiceSandbox,IsolateOrigins,site-per-process,Vulkan",
        "--use-fake-ui-for-media-stream",
        "--auto-select-desktop-capture-source=Entire screen",
        "--enable-usermedia-screen-capturing",
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
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
            cmd,
            env=clean_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        stream_process_logs(proc, "Browser")

        def check_browser_health():
            time.sleep(3.0)
            ret = proc.poll()
            if ret is not None:
                log(f"CRITICAL: Browser terminated unexpectedly shortly after launch! Exit code: {ret}")
                log("Examine any [Browser stderr] lines above in this log to diagnose the crash.")
            else:
                log("Browser process is active and running normally.")

        threading.Thread(target=check_browser_health, daemon=True).start()
        return proc
    except Exception as e:
        log(f"CRITICAL: Failed to spawn browser process: {e}")
        return None