import os
import sys
import json
import time
import shutil
import socket
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

# Allow Qt to use xcb fallback on Wayland for 100% overlay compatibility
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"

from PySide6.QtCore import Qt, QObject, Signal, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QPushButton, QLabel, 
    QGraphicsDropShadowEffect
)
from PySide6.QtGui import QColor, QMouseEvent

PORT = 5055
ROOM_NAME = "a"

def get_base_dir():
    """Returns the base directory whether running as script or frozen PyInstaller binary."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def get_clean_host_env():
    """Strips AppImage and PyInstaller specific variables so host processes don't crash on library conflicts."""
    env = os.environ.copy()
    vars_to_remove = [
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PYTHONPATH",
        "PYTHONHOME",
        "QT_PLUGIN_PATH",
        "QML2_IMPORT_PATH"
    ]
    for var in vars_to_remove:
        env.pop(var, None)
    return env

def detect_lan_ip():
    """Automatically detects the real Wi-Fi / Ethernet IPv4 address, filtering out virtual/TUN/198.18.x subnets."""
    try:
        res = subprocess.run(["ip", "-4", "-o", "addr", "show"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        candidates = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                ifname = parts[1]
                ip_cidr = parts[3]
                ip = ip_cidr.split("/")[0]
                
                # Exclude loopback, link-local, and VPN / Proxy TUN subnets (such as 198.18.x.x)
                if ip.startswith("127.") or ip.startswith("198.18.") or ip.startswith("169.254."):
                    continue
                if any(ifname.startswith(p) for p in ["lo", "docker", "veth", "br-", "tun", "tap", "wg", "tailscale"]):
                    continue
                candidates.append((ifname, ip))

        # Prioritize wireless (wl*) and ethernet (eth*, en*)
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
    """Terminates any stale processes using Screego/Control ports."""
    ports = ["5050/tcp", "5055/tcp", "3478/tcp", "3478/udp"]
    for port in ports:
        subprocess.run(["fuser", "-k", port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_audio_cmd(args):
    """Executes pactl commands directly."""
    try:
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

original_default_source = None
remap_module_id = None
active_audio_source_name = None

def setup_pipewire_audio():
    """
    Multi-tiered audio capture solution compatible with PulseAudio and PipeWire.
    Tier 1: Attempts to create an isolated VirtualMic using module-remap-source from default sink monitor.
    Tier 2: If dynamic module loading is disabled, directly switches the default audio source to the active monitor source.
    """
    global original_default_source, remap_module_id, active_audio_source_name
    try:
        res_src = subprocess.run(["pactl", "get-default-source"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        original_default_source = res_src.stdout.strip()

        res_sink = subprocess.run(["pactl", "get-default-sink"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        default_sink = res_sink.stdout.strip()
        if not default_sink:
            return

        monitor_source = f"{default_sink}.monitor"

        load_res = subprocess.run([
            "pactl", "load-module", "module-remap-source",
            "source_name=VirtualMic",
            f"master={monitor_source}",
            "source_properties=device.description=VirtualMic"
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

        if load_res.returncode == 0 and load_res.stdout.strip().isdigit():
            remap_module_id = load_res.stdout.strip()
            active_audio_source_name = "VirtualMic"
            run_audio_cmd(["pactl", "set-default-source", "VirtualMic"])
            run_audio_cmd(["pactl", "set-source-mute", "VirtualMic", "0"])
            run_audio_cmd(["pactl", "set-source-volume", "VirtualMic", "100%"])
        else:
            active_audio_source_name = monitor_source
            run_audio_cmd(["pactl", "set-default-source", monitor_source])
            run_audio_cmd(["pactl", "set-source-mute", monitor_source, "0"])
    except Exception as e:
        print(f"Warning: Audio setup encountered: {e}")

def cleanup_audio():
    """Restores the original microphone source and unloads temporary audio modules."""
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

def find_or_build_screego():
    """Locates the screego binary across server/, root, and parent directories or auto-builds it."""
    search_dirs = [
        os.path.join(BASE_DIR, "server"),
        BASE_DIR,
        os.path.join(os.getcwd(), "server"),
        os.getcwd(),
        os.path.join(os.path.dirname(BASE_DIR), "server"),
        os.path.dirname(BASE_DIR)
    ]

    for d in search_dirs:
        bin_path = os.path.join(d, "screego")
        if os.path.isfile(bin_path):
            if not os.access(bin_path, os.X_OK):
                try:
                    os.chmod(bin_path, 0o755)
                except Exception:
                    pass
            return bin_path

    in_path = shutil.which("screego")
    if in_path:
        return in_path

    go_bins = [
        shutil.which("go"),
        os.path.expanduser("~/.local/go/bin/go"),
        os.path.expanduser("~/go/bin/go"),
        "/usr/local/go/bin/go",
        "/usr/bin/go"
    ]
    go_cmd = next((g for g in go_bins if g and os.path.isfile(g)), None)

    if go_cmd:
        src_dir = None
        for d in search_dirs:
            if os.path.isfile(os.path.join(d, "main.go")):
                src_dir = d
                break

        if src_dir:
            print("========================================")
            print(f"Screego binary missing. Compiling in: {src_dir}")
            print("========================================")
            
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
                    print("Building React frontend with Deno...")
                    subprocess.run([deno_cmd, "install"], cwd=ui_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.run([deno_cmd, "task", "build"], cwd=ui_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            out_bin = os.path.join(src_dir, "screego")
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

def start_screego_server(lan_ip):
    """Spawns the Screego backend binary."""
    screego_bin = find_or_build_screego()

    if not screego_bin or not os.path.isfile(screego_bin):
        print("========================================")
        print("Error: Screego executable binary not found.")
        print("Please build it once by running: go build -o screego .")
        print("========================================")
        sys.exit(1)

    bin_dir = os.path.dirname(os.path.abspath(screego_bin))
    print(f"Using Screego binary: {screego_bin}")
    print(f"Working Directory  : {bin_dir}")

    env = os.environ.copy()
    env["SCREEGO_EXTERNAL_IP"] = lan_ip
    env["SCREEGO_SERVER_ADDRESS"] = "0.0.0.0:5050"
    env["SCREEGO_TURN_ADDRESS"] = "0.0.0.0:3478"
    env["SCREEGO_AUTH_MODE"] = "turn"
    env["SCREEGO_CLOSE_ROOM_WHEN_OWNER_LEAVES"] = "true"
    env["SCREEGO_LOG_LEVEL"] = "info"
    
    users_candidates = [
        os.path.join(bin_dir, "users"),
        os.path.join(BASE_DIR, "users"),
        os.path.join(BASE_DIR, "server", "users"),
        os.path.join(os.getcwd(), "users"),
        os.path.join(os.getcwd(), "server", "users")
    ]
    for u_path in users_candidates:
        if os.path.isfile(u_path):
            env["SCREEGO_USERS_FILE"] = os.path.abspath(u_path)
            break

    proc = subprocess.Popen([screego_bin, "serve"], env=env, cwd=bin_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc

def launch_hidden_browser(url):
    """Finds and launches Edge/Chromium on host system with clean environment."""
    executable_cmd = []

    search_binaries = [
        "microsoft-edge-stable",
        "microsoft-edge",
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "brave",
        "vivaldi",
        "microsoft-edge-beta",
        "microsoft-edge-dev",
        "google-chrome-beta",
        "google-chrome-unstable"
    ]

    for binary in search_binaries:
        path = shutil.which(binary)
        if path:
            executable_cmd = [path]
            break

    if not executable_cmd and shutil.which("flatpak"):
        for app_id in ["com.microsoft.Edge", "com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser"]:
            res = subprocess.run(["flatpak", "info", app_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                executable_cmd = ["flatpak", "run", app_id]
                break

    if not executable_cmd:
        print("Warning: No compatible Chromium or Edge browser found on host system.")
        return None

    cmd = executable_cmd + [
        f"--app={url}",
        "--ozone-platform-hint=auto",
        "--enable-features=WebRTCPipeWireCapturer,VaapiVideoEncoder,VaapiVideoDecoder,CanvasOopRasterization",
        "--disable-features=AudioServiceOutOfProcess,AudioServiceSandbox",
        "--use-fake-ui-for-media-stream",
        "--auto-select-desktop-capture-source=Entire screen",
        "--enable-usermedia-screen-capturing",
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--autoplay-policy=no-user-gesture-required",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-logging",
        "--log-level=3",
        "--disable-breakpad",
        "--disable-component-update"
    ]
    
    clean_env = get_clean_host_env()
    print(f"Launching browser command: {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=clean_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        self.audio_muted = False
        self.is_collapsed = False
        self._drag_pos = QPoint()
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

        self.indicator = InteractiveIndicator("●", self.container)
        self.indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.indicator.setToolTip(f"Screego running on http://{self.lan_ip}:5050\nClick to collapse/expand")
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

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        self.grip.setVisible(not self.is_collapsed)
        self.btn_share.setVisible(not self.is_collapsed)
        self.btn_pause.setVisible(not self.is_collapsed)
        self.btn_mute.setVisible(not self.is_collapsed)
        self.btn_exit.setVisible(not self.is_collapsed)
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
    kill_port_owners()
    time.sleep(0.5)

    lan_ip = detect_lan_ip()
    print("========================================")
    print(f" Detected Local IP : {lan_ip}")
    print(f" Viewers can join  : http://{lan_ip}:5050")
    print("========================================")

    setup_pipewire_audio()

    screego_proc = start_screego_server(lan_ip)
    time.sleep(1.0)

    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    room_url = f"http://127.0.0.1:5050/?room={ROOM_NAME}&create=true"
    browser_proc = launch_hidden_browser(room_url)

    app = QApplication(sys.argv)
    toolbar = OverlayToolbar(lan_ip)
    toolbar.show()

    def cleanup():
        if browser_proc:
            browser_proc.terminate()
            try:
                browser_proc.wait(timeout=2)
            except Exception:
                browser_proc.kill()

        if screego_proc:
            screego_proc.terminate()
            try:
                screego_proc.wait(timeout=2)
            except Exception:
                screego_proc.kill()

        cleanup_audio()

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())