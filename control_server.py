import os
import sys
import json
import time
import shutil
import socket
import tempfile
import datetime
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
import urllib.request

# Allow Qt to use xcb fallback on Wayland for 100% overlay compatibility
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"

from PySide6.QtCore import Qt, QObject, Signal, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, 
    QGraphicsDropShadowEffect
)
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPixmap

PORT = 5055
ROOM_NAME = "a"

def get_base_dir():
    """Returns the base directory whether running as script or frozen PyInstaller binary."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

# AppImage sets $OWD to the directory where the user launched the application
EXECUTION_DIR = os.environ.get("OWD", os.getcwd())
LOG_FILE_PATH = os.path.join(EXECUTION_DIR, "ScreenShare-host.log")

def log(msg):
    """Outputs timestamped message to stdout and appends to ScreenShare-host.log in run directory."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception as e:
        print(f"Failed to write to log file {LOG_FILE_PATH}: {e}")

# =====================================================================
# PURE-PYTHON QR CODE GENERATOR (COMPLIANT WITH ISO/IEC 18004)
# =====================================================================
GF_EXP = [0] * 512
GF_LOG = [0] * 256

def _init_gf():
    x = 1
    for i in range(255):
        GF_EXP[i] = x
        GF_EXP[i + 255] = x
        GF_LOG[x] = i
        x <<= 1
        if x & 256:
            x ^= 0x11D

_init_gf()

def gf_mul(x, y):
    if x == 0 or y == 0:
        return 0
    return GF_EXP[GF_LOG[x] + GF_LOG[y]]

def rs_generator_poly(degree):
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        root = GF_EXP[i]
        for j in range(len(poly)):
            next_poly[j] ^= gf_mul(poly[j], root)
            next_poly[j + 1] ^= poly[j]
        poly = next_poly
    return poly

def rs_encode(data, num_ec_bytes):
    gen = rs_generator_poly(num_ec_bytes)
    msg = data + [0] * num_ec_bytes
    for i in range(len(data)):
        coef = msg[i]
        if coef != 0:
            for j in range(len(gen)):
                msg[i + j] ^= gf_mul(gen[j], coef)
    return msg[len(data):]

VERSION_SPECS = [
    {"version": 1, "size": 21, "totalCodewords": 26, "dataCodewords": 19, "ecCodewords": 7, "alignment": []},
    {"version": 2, "size": 25, "totalCodewords": 44, "dataCodewords": 34, "ecCodewords": 10, "alignment": [6, 18]},
    {"version": 3, "size": 29, "totalCodewords": 70, "dataCodewords": 55, "ecCodewords": 15, "alignment": [6, 22]},
    {"version": 4, "size": 33, "totalCodewords": 100, "dataCodewords": 80, "ecCodewords": 20, "alignment": [6, 26]},
    {"version": 5, "size": 37, "totalCodewords": 134, "dataCodewords": 108, "ecCodewords": 26, "alignment": [6, 30]},
    {"version": 6, "size": 41, "totalCodewords": 172, "dataCodewords": 136, "ecCodewords": 36, "alignment": [6, 34]},
    {"version": 7, "size": 45, "totalCodewords": 196, "dataCodewords": 156, "ecCodewords": 40, "alignment": [6, 22, 38]},
]

def generate_qr_matrix(text: str):
    utf8_bytes = list(text.encode("utf-8"))
    data_len = len(utf8_bytes)

    spec = next((s for s in VERSION_SPECS if s["dataCodewords"] >= data_len + 3), VERSION_SPECS[-1])
    size = spec["size"]

    bits = []
    def push_bits(val, length):
        for i in range(length - 1, -1, -1):
            bits.append((val >> i) & 1)

    push_bits(0b0100, 4)       # Byte mode
    push_bits(data_len, 8)     # Character count
    for b in utf8_bytes:
        push_bits(b, 8)

    total_data_bits = spec["dataCodewords"] * 8
    term_len = min(4, total_data_bits - len(bits))
    push_bits(0, term_len)

    while len(bits) % 8 != 0:
        bits.append(0)

    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(bits) < total_data_bits:
        push_bits(pad_bytes[pad_idx % 2], 8)
        pad_idx += 1

    data_bytes = []
    for i in range(0, len(bits), 8):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[i + j]
        data_bytes.append(b)

    ec_bytes = rs_encode(data_bytes, spec["ecCodewords"])
    final_codewords = data_bytes + ec_bytes

    matrix = [[None] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_func(r, c, val):
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = val
            is_func[r][c] = True

    def draw_finder(r0, c0):
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < size and 0 <= c0 + c < size:
                    is_black = (0 <= r <= 6 and (c == 0 or c == 6)) or \
                               (0 <= c <= 6 and (r == 0 or r == 6)) or \
                               (2 <= r <= 4 and 2 <= c <= 4)
                    set_func(r0 + r, c0 + c, is_black)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    for i in range(8, size - 8):
        set_func(6, i, i % 2 == 0)
        set_func(i, 6, i % 2 == 0)

    if spec["alignment"]:
        for ar in spec["alignment"]:
            for ac in spec["alignment"]:
                if (ar <= 8 and ac <= 8) or (ar <= 8 and ac >= size - 8) or (ar >= size - 8 and ac <= 8):
                    continue
                for r in range(-2, 3):
                    for c in range(-2, 3):
                        set_func(ar + r, ac + c, max(abs(r), abs(c)) != 1)

    set_func(size - 8, 8, True)
    for i in range(9):
        if 0 <= i < size:
            if not is_func[8][i]: set_func(8, i, False)
            if not is_func[i][8]: set_func(i, 8, False)
    for i in range(8):
        if 0 <= size - 1 - i < size:
            if not is_func[8][size - 1 - i]: set_func(8, size - 1 - i, False)
            if not is_func[size - 1 - i][8]: set_func(size - 1 - i, 8, False)

    byte_idx = 0
    bit_idx = 7
    up = True

    for right in range(size - 1, 0, -2):
        if right == 6:
            right -= 1
        for vert in range(size):
            r = size - 1 - vert if up else vert
            for c in (right, right - 1):
                if not is_func[r][c]:
                    bit = False
                    if byte_idx < len(final_codewords):
                        bit = ((final_codewords[byte_idx] >> bit_idx) & 1) == 1
                        bit_idx -= 1
                        if bit_idx < 0:
                            bit_idx = 7
                            byte_idx += 1
                    matrix[r][c] = bit
        up = not up

    final_result = [[False] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            if is_func[r][c]:
                final_result[r][c] = bool(matrix[r][c])
            else:
                final_result[r][c] = bool(matrix[r][c]) ^ (((r + c) % 2) == 0)

    # Standard ISO/IEC 18004 Format Information for Error Correction Level L, Mask 0 (0x77c4)
    format_bits = 0x77C4
    def get_fbit(i):
        return ((format_bits >> i) & 1) == 1

    # Copy 1 (Around top-left finder)
    for i in range(6):
        final_result[8][i] = get_fbit(i)
    final_result[8][7] = get_fbit(6)
    final_result[8][8] = get_fbit(7)
    final_result[7][8] = get_fbit(8)
    for i in range(9, 15):
        final_result[14 - i][8] = get_fbit(i)

    # Copy 2 (Split across bottom-left and top-right finders)
    for i in range(8):
        final_result[size - 1 - i][8] = get_fbit(i)
    for i in range(8, 15):
        final_result[8][size - 15 + i] = get_fbit(i)
    final_result[size - 8][8] = True  # Always dark module

    return final_result

def get_qr_pixmap(text: str):
    """Renders QR code to a high-contrast QPixmap with standard 4-module quiet zone margin."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        border = 0
    except Exception:
        matrix = generate_qr_matrix(text)
        border = 4

    size = len(matrix)
    scale = 8
    total_dim = (size + border * 2) * scale
    pixmap = QPixmap(total_dim, total_dim)
    pixmap.fill(QColor("#ffffff"))

    painter = QPainter(pixmap)
    painter.setBrush(QColor("#000000"))
    painter.setPen(Qt.PenStyle.NoPen)

    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                painter.drawRect((c + border) * scale, (r + border) * scale, scale, scale)

    painter.end()
    return pixmap

# =====================================================================
# SYSTEM & ENVIRONMENT HELPERS
# =====================================================================
def get_clean_host_env():
    """Strips AppImage and PyInstaller specific variables so host processes don't crash."""
    env = os.environ.copy()
    vars_to_remove = [
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PYTHONPATH",
        "PYTHONHOME",
        "QT_PLUGIN_PATH",
        "QML2_IMPORT_PATH",
        "GSETTINGS_SCHEMA_DIR",
        "GTK_PATH",
        "GTK_MODULES",
        "GTK_EXE_PREFIX",
        "FONTCONFIG_PATH",
        "FONTCONFIG_FILE",
        "APPIMAGE",
        "APPDIR",
        "ARGV0"
    ]
    for var in vars_to_remove:
        env.pop(var, None)

    current_path = env.get("PATH", "")
    paths = [p for p in current_path.split(":") if not p.startswith("/tmp/.mount_")]
    extra_paths = [
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/local/sbin",
        "/usr/sbin",
        "/sbin",
        "/snap/bin",
        "/var/lib/flatpak/exports/bin",
        os.path.expanduser("~/.local/share/flatpak/exports/bin"),
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/bin"),
    ]
    for ep in extra_paths:
        if ep not in paths:
            paths.append(ep)
    env["PATH"] = ":".join(paths)

    xdg_data = env.get("XDG_DATA_DIRS", "")
    if xdg_data:
        cleaned_dirs = [d for d in xdg_data.split(":") if not d.startswith("/tmp/.mount_")]
        standard_xdg = [
            os.path.expanduser("~/.local/share/flatpak/exports/share"),
            "/var/lib/flatpak/exports/share",
            "/usr/local/share",
            "/usr/share"
        ]
        for s in standard_xdg:
            if s not in cleaned_dirs:
                cleaned_dirs.append(s)
        env["XDG_DATA_DIRS"] = ":".join(cleaned_dirs)
    else:
        env["XDG_DATA_DIRS"] = f"{os.path.expanduser('~/.local/share/flatpak/exports/share')}:/var/lib/flatpak/exports/share:/usr/local/share:/usr/share"

    return env

def detect_lan_ip():
    """Automatically detects the real Wi-Fi / Ethernet IPv4 address, filtering out virtual/TUN subnets."""
    clean_env = get_clean_host_env()
    try:
        res = subprocess.run(["ip", "-4", "-o", "addr", "show"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)
        candidates = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                ifname = parts[1]
                ip = parts[3].split("/")[0]
                
                if ip.startswith("127.") or ip.startswith("198.18.") or ip.startswith("169.254."):
                    continue
                if any(ifname.startswith(p) for p in ["lo", "docker", "veth", "br-", "tun", "tap", "wg", "tailscale"]):
                    continue
                candidates.append((ifname, ip))

        for ifname, ip in candidates:
            if ifname.startswith("wl") or ifname.startswith("eth") or ifname.startswith("en"):
                return ip
        if candidates:
            return candidates[0][1]
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("198.18.") and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return "127.0.0.1"

def kill_port_owners():
    """Terminates any stale processes using ScreenShare/Control ports."""
    clean_env = get_clean_host_env()
    ports = ["5050/tcp", "5055/tcp", "3478/tcp", "3478/udp"]
    for port in ports:
        subprocess.run(["fuser", "-k", port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)

def run_audio_cmd(args):
    """Executes pactl commands directly."""
    clean_env = get_clean_host_env()
    try:
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)
    except Exception:
        pass

original_default_source = None
remap_module_id = None
active_audio_source_name = None

def setup_pipewire_audio():
    """Sets up virtual audio sink / mic monitoring for screen sharing."""
    global original_default_source, remap_module_id, active_audio_source_name
    clean_env = get_clean_host_env()
    try:
        res_src = subprocess.run(["pactl", "get-default-source"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)
        original_default_source = res_src.stdout.strip()

        res_sink = subprocess.run(["pactl", "get-default-sink"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)
        default_sink = res_sink.stdout.strip()
        if not default_sink:
            return

        monitor_source = f"{default_sink}.monitor"

        load_res = subprocess.run([
            "pactl", "load-module", "module-remap-source",
            "source_name=VirtualMic",
            f"master={monitor_source}",
            "source_properties=device.description=VirtualMic"
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)

        if load_res.returncode == 0 and load_res.stdout.strip().isdigit():
            remap_module_id = load_res.stdout.strip()
            active_audio_source_name = "VirtualMic"
            run_audio_cmd(["pactl", "set-default-source", "VirtualMic"])
            run_audio_cmd(["pactl", "set-source-mute", "VirtualMic", "0"])
            run_audio_cmd(["pactl", "set-source-volume", "VirtualMic", "100%"])
            log("Audio setup: Loaded module-remap-source (VirtualMic)")
        else:
            active_audio_source_name = monitor_source
            run_audio_cmd(["pactl", "set-default-source", monitor_source])
            run_audio_cmd(["pactl", "set-source-mute", monitor_source, "0"])
            log(f"Audio setup: Default source fallback to {monitor_source}")
    except Exception as e:
        log(f"Warning: Audio setup encountered: {e}")

def cleanup_audio():
    """Restores the original audio default source."""
    global original_default_source, remap_module_id
    if remap_module_id:
        run_audio_cmd(["pactl", "unload-module", remap_module_id])
    else:
        run_audio_cmd(["pactl", "unload-module", "module-remap-source"])

    if original_default_source:
        run_audio_cmd(["pactl", "set-default-source", original_default_source])

class CommSignals(QObject):
    state_updated = Signal(dict)

comm = CommSignals()
app_state = {"sharing": False, "paused": False}
pending_action = None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, *')
        self.end_headers()

    def do_GET(self):
        global pending_action
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()

        if self.path == '/poll':
            if pending_action:
                self.wfile.write(json.dumps({"action": pending_action}).encode())
                pending_action = None
            else:
                self.wfile.write(b'{"action": "none"}')

    def do_POST(self):
        global app_state
        if self.path == '/state':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
                try:
                    data = json.loads(post_data.decode('utf-8'))
                    app_state = data
                    comm.state_updated.emit(data)
                except Exception:
                    pass
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

class ThreadingHTTPServer(ThreadingTCPServer, HTTPServer):
    pass

def run_http_server():
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    server.serve_forever()

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

    target_names = ["ScreenShare", "screenshare"]

    for d in search_dirs:
        for name in target_names:
            bin_path = os.path.join(d, name)
            if os.path.isfile(bin_path):
                if not os.access(bin_path, os.X_OK):
                    try:
                        os.chmod(bin_path, 0o755)
                    except Exception:
                        pass
                return bin_path

    for name in target_names:
        in_path = shutil.which(name)
        if in_path:
            return in_path

    go_bins = [
        shutil.which("go"),
        os.path.expanduser("~/.local/go/bin/go"),
        os.path.expanduser("~/go/bin/go"),
        "/usr/local/go/bin/go",
        "/usr/bin/go"
    ]
    go_cmd = next((g for g in go_bins if g and os.path.isfile(go_cmd or "")), None)

    if go_cmd:
        src_dir = None
        for d in search_dirs:
            if os.path.isfile(os.path.join(d, "main.go")):
                src_dir = d
                break

        if src_dir:
            log("========================================")
            log(f"Backend binary missing. Compiling in: {src_dir}")
            log("========================================")
            
            ui_dist = os.path.join(src_dir, "ui", "build")
            if not os.path.isdir(ui_dist):
                deno_bins = [
                    shutil.which("deno"),
                    os.path.expanduser("~/.deno/bin/deno"),
                    os.path.expanduser("~/.local/bin/deno")
                ]
                deno_cmd = next((d for d in deno_bins if d and os.path.isfile(d)), None)
                ui_dir = os.path.join(src_dir, "ui")
                if deno_cmd and os.path.isdir(ui_dir):
                    log("Building React frontend with Deno...")
                    subprocess.run([deno_cmd, "install"], cwd=ui_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.run([deno_cmd, "task", "build"], cwd=ui_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            out_bin = os.path.join(src_dir, "ScreenShare")
            env = os.environ.copy()
            env["CGO_ENABLED"] = "0"
            build_res = subprocess.run(
                [go_cmd, "build", "-ldflags=-s -w -X main.mode=prod", "-o", out_bin, "."],
                cwd=src_dir,
                env=env
            )
            if build_res.returncode == 0 and os.path.isfile(out_bin):
                os.chmod(out_bin, 0o755)
                return out_bin

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
        log("========================================")
        log("Error: Server executable binary not found.")
        log("Please build it once by running: go build -o ScreenShare .")
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

def wait_for_server(url, timeout=6.0):
    """Waits until the local HTTP server is responsive before opening browser."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status in (200, 302, 304):
                    log(f"Backend server is up and responsive at {url}")
                    return True
        except Exception:
            time.sleep(0.2)
    log(f"Warning: Backend server did not respond at {url} within {timeout} seconds. Proceeding anyway.")
    return False

def find_browser_executable():
    """Searches for Microsoft Edge, Chrome, or Chromium across host paths, Snaps, and Flatpaks."""
    clean_env = get_clean_host_env()
    search_binaries = [
        "microsoft-edge-stable",
        "microsoft-edge",
        "msedge",
        "com.microsoft.Edge",
        "google-chrome-stable",
        "google-chrome",
        "chrome",
        "com.google.Chrome",
        "chromium",
        "chromium-browser",
        "org.chromium.Chromium",
        "brave-browser",
        "brave",
        "com.brave.Browser",
        "vivaldi",
        "vivaldi-stable",
        "microsoft-edge-beta",
        "microsoft-edge-dev",
        "google-chrome-beta",
        "google-chrome-unstable"
    ]

    explicit_dirs = [
        "/usr/bin",
        "/usr/local/bin",
        "/bin",
        "/snap/bin",
        "/var/lib/flatpak/exports/bin",
        os.path.expanduser("~/.local/share/flatpak/exports/bin"),
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/bin"),
        "/opt/microsoft/msedge",
        "/opt/microsoft/msedge-beta",
        "/opt/microsoft/msedge-dev",
        "/opt/google/chrome",
        "/opt/brave.com/brave",
        "/app/bin"
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
        "/usr/bin/flatpak",
        "/usr/local/bin/flatpak",
        "/var/lib/flatpak",
    ]
    flatpak_bin = next((f for f in flatpak_candidates if f and os.path.isfile(f) and os.access(f, os.X_OK)), None)
    
    app_ids = [
        "com.microsoft.Edge",
        "com.microsoft.Edge.Dev",
        "com.microsoft.Edge.Beta",
        "com.google.Chrome",
        "com.google.Chrome.Dev",
        "com.google.Chrome.Beta",
        "org.chromium.Chromium",
        "com.brave.Browser"
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

# =====================================================================
# PY-SIDE 6 GUI OVERLAYS
# =====================================================================
class QROverlayDialog(QWidget):
    """Floating QR Code popup card. Clicking anywhere on it closes it."""
    def __init__(self, join_url):
        super().__init__()
        self.join_url = join_url
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        self.container = QWidget(self)
        self.container.setObjectName("QRContainer")
        self.container.setStyleSheet("""
            QWidget#QRContainer {
                background-color: rgba(28, 28, 28, 250);
                border: 2px solid #fabd2f;
                border-radius: 16px;
            }
            QLabel {
                border: none;
                background: transparent;
                color: #fbf1c7;
                font-family: sans-serif;
            }
        """)

        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(18, 18, 18, 18)
        c_layout.setSpacing(10)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Scan with Phone to Join", self.container)
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #fabd2f;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(title)

        pixmap = get_qr_pixmap(self.join_url)

        self.qr_img = QLabel(self.container)
        self.qr_img.setPixmap(pixmap)
        self.qr_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_img.setCursor(Qt.CursorShape.PointingHandCursor)
        c_layout.addWidget(self.qr_img)

        url_label = QLabel(self.join_url, self.container)
        url_label.setStyleSheet("font-size: 12px; color: #8ec07c; font-weight: bold;")
        url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(url_label)

        hint = QLabel("(Click anywhere on this card to close)", self.container)
        hint.setStyleSheet("font-size: 11px; color: #a89984; font-style: italic;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(hint)

        layout.addWidget(self.container)
        self.setLayout(layout)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 6)
        self.container.setGraphicsEffect(shadow)

    def mousePressEvent(self, event: QMouseEvent):
        self.hide()

class InteractiveIndicator(QLabel):
    clicked = Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._drag_start_pos = None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self.window().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start_pos:
            moved_dist = (event.globalPosition().toPoint() - self._drag_start_pos).manhattanLength()
            if moved_dist < 6:
                self.clicked.emit()
            self._drag_start_pos = None

    def mouseMoveEvent(self, event: QMouseEvent):
        self.window().mouseMoveEvent(event)

class OverlayToolbar(QWidget):
    def __init__(self, lan_ip):
        super().__init__()
        self.lan_ip = lan_ip
        self.viewer_url = f"http://{self.lan_ip}:5050/?room={ROOM_NAME}&create=true"
        self.audio_muted = False
        self.is_collapsed = False
        self._drag_pos = QPoint()
        self.qr_dialog = QROverlayDialog(self.viewer_url)
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetFixedSize)

        self.container = QWidget(self)
        self.container.setObjectName("Container")
        self.container.setStyleSheet("""
            QWidget#Container {
                background-color: rgba(40, 40, 40, 235);
                border: 1px solid #458588;
                border-radius: 12px;
            }
            QPushButton {
                background-color: #3c3836;
                color: #fbf1c7;
                border: none;
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
                font-family: sans-serif;
            }
            QPushButton:hover {
                background-color: #504945;
            }
            QPushButton:pressed {
                background-color: #665c54;
            }
            QPushButton:disabled {
                background-color: #1d2021;
                color: #928374;
            }
            QPushButton#QRBtn {
                background-color: #fabd2f;
                color: #282828;
            }
            QPushButton#QRBtn:hover {
                background-color: #d79921;
            }
            QPushButton#ExitBtn:hover {
                background-color: #cc241d;
                color: white;
            }
            QPushButton#ExitBtn:pressed {
                background-color: #9d0006;
            }
            QLabel {
                color: #a89984;
                font-family: sans-serif;
                font-size: 11px;
                font-weight: bold;
            }
        """)

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(6, 4, 6, 4)
        container_layout.setSpacing(4)

        self.grip = QLabel(" ⠿ ", self.container)
        self.grip.setCursor(Qt.CursorShape.SizeAllCursor)
        container_layout.addWidget(self.grip)

        self.btn_share = QPushButton("Share", self.container)
        self.btn_share.clicked.connect(self.toggle_share)
        container_layout.addWidget(self.btn_share)

        self.btn_pause = QPushButton("Pause", self.container)
        self.btn_pause.clicked.connect(self.trigger_pause)
        self.btn_pause.setEnabled(False)
        container_layout.addWidget(self.btn_pause)

        self.btn_mute = QPushButton("Mute", self.container)
        self.btn_mute.clicked.connect(self.toggle_mute)
        container_layout.addWidget(self.btn_mute)

        self.btn_qr = QPushButton("QR", self.container)
        self.btn_qr.setObjectName("QRBtn")
        self.btn_qr.setToolTip("Show QR code for phone scan")
        self.btn_qr.clicked.connect(self.toggle_qr)
        container_layout.addWidget(self.btn_qr)

        self.indicator = InteractiveIndicator("●", self.container)
        self.indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.indicator.setToolTip(f"ScreenShare running on {self.viewer_url}\nClick to collapse/expand\nLog: {LOG_FILE_PATH}")
        self.set_indicator_color("#b8bb26")
        self.indicator.clicked.connect(self.toggle_collapse)
        container_layout.addWidget(self.indicator)
        
        self.btn_exit = QPushButton("Exit", self.container)
        self.btn_exit.setObjectName("ExitBtn")
        self.btn_exit.clicked.connect(QApplication.instance().quit)
        container_layout.addWidget(self.btn_exit)

        layout.addWidget(self.container)
        self.setLayout(layout)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 3)
        self.container.setGraphicsEffect(shadow)

        comm.state_updated.connect(self.update_gui_state)
        self.move(30, 80)

    def set_indicator_color(self, color_hex):
        self.indicator.setStyleSheet(f"color: {color_hex}; font-size: 13px; padding: 0 4px;")

    def toggle_qr(self):
        if self.qr_dialog.isVisible():
            self.qr_dialog.hide()
        else:
            tb_pos = self.pos()
            self.qr_dialog.move(tb_pos.x() + self.width() + 10, tb_pos.y())
            self.qr_dialog.show()

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        self.grip.setVisible(not self.is_collapsed)
        self.btn_share.setVisible(not self.is_collapsed)
        self.btn_pause.setVisible(not self.is_collapsed)
        self.btn_mute.setVisible(not self.is_collapsed)
        self.btn_qr.setVisible(not self.is_collapsed)
        self.btn_exit.setVisible(not self.is_collapsed)
        if self.is_collapsed and self.qr_dialog.isVisible():
            self.qr_dialog.hide()
        self.container.adjustSize()
        self.adjustSize()

    def toggle_share(self):
        global pending_action
        if app_state["sharing"]:
            pending_action = "stop_share"
        else:
            pending_action = "start_share"

    def trigger_pause(self):
        global pending_action
        pending_action = "toggle_pause"

    def toggle_mute(self):
        global active_audio_source_name
        self.audio_muted = not self.audio_muted
        source_to_mute = active_audio_source_name or "VirtualMic"
        if self.audio_muted:
            self.btn_mute.setText("Unmute")
            self.btn_mute.setStyleSheet("background-color: #cc241d; color: white;")
            run_audio_cmd(["pactl", "set-source-mute", source_to_mute, "1"])
        else:
            self.btn_mute.setText("Mute")
            self.btn_mute.setStyleSheet("")
            run_audio_cmd(["pactl", "set-source-mute", source_to_mute, "0"])

    def update_gui_state(self, state):
        if state["sharing"]:
            self.btn_share.setText("Stop")
            self.btn_share.setStyleSheet("background-color: #cc241d; color: white;")
            self.btn_pause.setEnabled(True)
            if state["paused"]:
                self.btn_pause.setText("Resume")
                self.btn_pause.setStyleSheet("background-color: #fabd2f; color: black;")
                self.set_indicator_color("#fabd2f")
            else:
                self.btn_pause.setText("Pause")
                self.btn_pause.setStyleSheet("")
                self.set_indicator_color("#fe8019")
        else:
            self.btn_share.setText("Share")
            self.btn_share.setStyleSheet("")
            self.btn_pause.setText("Pause")
            self.btn_pause.setStyleSheet("")
            self.btn_pause.setEnabled(False)
            self.set_indicator_color("#b8bb26")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

if __name__ == '__main__':
    log("=================================================================")
    log(" ScreenShare Host Starting")
    log(f" Execution Working Dir : {EXECUTION_DIR}")
    log(f" Log File Location     : {LOG_FILE_PATH}")
    log(f" Python sys.executable : {sys.executable}")
    log(f" Frozen bundle status  : {getattr(sys, 'frozen', False)}")
    log("=================================================================")

    kill_port_owners()
    time.sleep(0.5)

    lan_ip = detect_lan_ip()
    log(f" Detected Local IP     : {lan_ip}")
    log(f" Viewers URL           : http://{lan_ip}:5050")

    setup_pipewire_audio()

    server_proc = start_screenshare_server(lan_ip)
    
    wait_for_server(f"http://127.0.0.1:5050/health", timeout=6.0)

    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    log(f"Local control bridge HTTP server listening on 127.0.0.1:{PORT}")

    room_url = f"http://127.0.0.1:5050/?room={ROOM_NAME}&create=true"
    browser_proc = launch_hidden_browser(room_url)

    app = QApplication(sys.argv)
    toolbar = OverlayToolbar(lan_ip)
    toolbar.show()

    def cleanup():
        log("Application shutdown initiated. Cleaning up subprocesses...")
        if toolbar.qr_dialog:
            toolbar.qr_dialog.close()

        if browser_proc:
            browser_proc.terminate()
            try:
                browser_proc.wait(timeout=2)
            except Exception:
                browser_proc.kill()

        if server_proc:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=2)
            except Exception:
                server_proc.kill()

        cleanup_audio()
        log("Cleanup finished. ScreenShare Host terminated.")

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())