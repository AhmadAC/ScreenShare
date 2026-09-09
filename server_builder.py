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

def is_real_ui_build(ui_dir):
    """Verifies that ui/build contains actual compiled React assets, not a dummy fallback."""
    build_dir = os.path.join(ui_dir, "build")
    index_file = os.path.join(build_dir, "index.html")
    assets_dir = os.path.join(build_dir, "assets")
    if not os.path.isfile(index_file) or not os.path.isdir(assets_dir):
        return False
    js_files = [f for f in os.listdir(assets_dir) if f.endswith(".js")]
    return len(js_files) > 0

def needs_rebuild(src_dir, out_bin):
    """Checks if server binary or real React production assets are missing or out of date."""
    if not os.path.isfile(out_bin):
        return True
    
    ui_dir = os.path.join(src_dir, "ui")
    if not is_real_ui_build(ui_dir):
        return True

    bin_mtime = os.path.getmtime(out_bin)
    ui_src = os.path.join(ui_dir, "src")
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

def link_or_copy_dir(src, dst):
    """Creates a directory junction or copies files without requiring administrator privileges on Windows."""
    if os.path.exists(dst):
        return
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if sys.platform.startswith("win"):
        try:
            import _winapi
            _winapi.CreateJunction(os.path.abspath(src), os.path.abspath(dst))
            if os.path.exists(dst):
                return
        except Exception:
            pass
        try:
            subprocess.run(["cmd", "/c", "mklink", "/J", os.path.abspath(dst), os.path.abspath(src)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(dst):
                return
        except Exception:
            pass
    try:
        shutil.copytree(src, dst, symlinks=False)
    except Exception as e:
        log(f"Notice during copytree: {e}")

def fix_deno_windows_node_modules(ui_dir):
    """Fixes Deno's missing package links on Windows by junctioning packages from .deno into node_modules."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    deno_store = os.path.join(nm_dir, ".deno")
    if not os.path.isdir(deno_store):
        return

    log("Resolving Windows package links from Deno store...")
    for entry in os.listdir(deno_store):
        entry_path = os.path.join(deno_store, entry)
        if not os.path.isdir(entry_path):
            continue
        inner_nm = os.path.join(entry_path, "node_modules")
        if not os.path.isdir(inner_nm):
            continue
        for pkg in os.listdir(inner_nm):
            pkg_path = os.path.join(inner_nm, pkg)
            if pkg.startswith("@"):
                for subpkg in os.listdir(pkg_path):
                    sub_src = os.path.join(pkg_path, subpkg)
                    sub_dst = os.path.join(nm_dir, pkg, subpkg)
                    if not os.path.exists(sub_dst) and os.path.isdir(sub_src):
                        link_or_copy_dir(sub_src, sub_dst)
            else:
                dst_path = os.path.join(nm_dir, pkg)
                if not os.path.exists(dst_path) and os.path.isdir(pkg_path):
                    link_or_copy_dir(pkg_path, dst_path)

    # Ensure rolldown and @rolldown are also directly in vite's nested node_modules
    rolldown_src = os.path.join(nm_dir, "rolldown")
    at_rolldown_src = os.path.join(nm_dir, "@rolldown")

    for root, _, _ in os.walk(deno_store):
        if os.path.basename(root) == "vite" and "node_modules" in os.path.dirname(root):
            vite_nm = os.path.join(root, "node_modules")
            if os.path.isdir(rolldown_src):
                link_or_copy_dir(rolldown_src, os.path.join(vite_nm, "rolldown"))
            if os.path.isdir(at_rolldown_src):
                for sub in os.listdir(at_rolldown_src):
                    sub_src = os.path.join(at_rolldown_src, sub)
                    if os.path.isdir(sub_src):
                        link_or_copy_dir(sub_src, os.path.join(vite_nm, "@rolldown", sub))

def fix_broken_vite_shims(ui_dir):
    """Detects and repairs npm/cmd-shim shell scripts mistakenly written to .js files in node_modules."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    if not os.path.isdir(nm_dir):
        return

    for root, _, files in os.walk(nm_dir):
        for f in files:
            if f == "vite.js":
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
                        header = fp.read(200)
                    if "basedir=" in header or "#!/bin/sh" in header or "dirname" in header:
                        log(f"Repairing shell-script corruption in {fpath}...")
                        parent_pkg = os.path.abspath(os.path.join(root, ".."))
                        target_cli = os.path.join(parent_pkg, "dist", "node", "cli.js")
                        if os.path.isfile(target_cli):
                            with open(fpath, "w", encoding="utf-8") as fp:
                                fp.write("import '../dist/node/cli.js';\n")
                            log(f"Successfully repaired {fpath} to import Vite CLI.")
                        else:
                            with open(fpath, "w", encoding="utf-8") as fp:
                                fp.write("import './dist/node/cli.js';\n")
                except Exception as e:
                    log(f"Notice while inspecting {fpath}: {e}")

def find_vite_cli(ui_dir):
    """Finds the actual Vite cli.js file in node_modules."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    if not os.path.isdir(nm_dir):
        return None
    for root, _, files in os.walk(nm_dir):
        if "cli.js" in files and ("dist" in root and "node" in root):
            candidate = os.path.join(root, "cli.js")
            if "vite" in candidate.lower():
                return candidate
    return None

def build_frontend_ui(src_dir, deno_cmd, pbar=None):
    """Builds the React frontend and guarantees ui/build contains real React assets for Go embed."""
    ui_dir = os.path.join(src_dir, "ui")
    ui_build_dir = os.path.join(ui_dir, "build")
    ui_public_dir = os.path.join(ui_dir, "public")

    if not os.path.isdir(ui_dir):
        return True

    # Remove any old dummy build
    if not is_real_ui_build(ui_dir):
        shutil.rmtree(ui_build_dir, ignore_errors=True)

    log("Building React frontend...")
    if pbar:
        pbar.update(10, task="Building UI", detail="Installing dependencies...")

    if deno_cmd:
        try:
            subprocess.run([deno_cmd, "install"], cwd=ui_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        except Exception as e:
            log(f"Deno install notice: {e}")

    # Repair shims and link .deno packages into node_modules
    fix_broken_vite_shims(ui_dir)
    fix_deno_windows_node_modules(ui_dir)

    if pbar:
        pbar.update(25, task="Building UI", detail="Running Vite bundler...")

    build_success = False

    # 1. Direct CLI execution via Deno
    cli_js = find_vite_cli(ui_dir)
    if cli_js and deno_cmd:
        try:
            log(f"Invoking Vite CLI directly: {cli_js}")
            res = subprocess.run([deno_cmd, "run", "-A", cli_js, "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with direct Vite CLI.")
            else:
                log(f"Direct Vite CLI notice: {res.stderr or res.stdout}")
        except Exception as e:
            log(f"Direct Vite CLI error: {e}")

    # 2. Deno task build fallback
    if not build_success and deno_cmd:
        try:
            res = subprocess.run([deno_cmd, "task", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with Deno task.")
            else:
                log(f"Deno task build notice: {res.stderr or res.stdout}")
        except Exception as e:
            log(f"Deno task build notice: {e}")

    # 3. Direct Deno npm specifier fallback
    if not build_success and deno_cmd:
        try:
            res = subprocess.run([deno_cmd, "run", "-A", "npm:vite", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with Deno npm:vite.")
            else:
                log(f"Deno npm:vite notice: {res.stderr or res.stdout}")
        except Exception as e:
            log(f"Deno npm:vite notice: {e}")

    # 4. Node / NPX fallback
    if not build_success:
        npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
        if npx_cmd:
            if pbar:
                pbar.update(35, task="Building UI", detail="Trying npx vite...")
            try:
                res = subprocess.run([npx_cmd, "--yes", "vite", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
                if res.returncode == 0 and is_real_ui_build(ui_dir):
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

    return is_real_ui_build(ui_dir)

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

    is_win = sys.platform.startswith("win")

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

    # Only include literal capture source selection on non-Windows to prevent picker mismatches
    if not is_win:
        cmd.append("--auto-select-desktop-capture-source=Entire screen")
    
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