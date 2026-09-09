import os
import sys
import time
import threading
import subprocess
import urllib.request
from system_util import log, BASE_DIR
from go_builder import find_or_build_binary

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
            log("To install Go on Windows, open PowerShell and run:")
            log("  winget install GoLang.Go")
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