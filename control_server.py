import sys
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

# Allow Qt to use xcb fallback on Wayland for 100% overlay compatibility
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"

# PySide6 Imports for Overlay Toolbar
from PySide6.QtCore import Qt, QObject, Signal, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QPushButton, QLabel, 
    QGraphicsDropShadowEffect
)
from PySide6.QtGui import QColor, QMouseEvent

PORT = 5055

SCREEGO_URL = "http://127.0.0.1:5050/?room=a&create=true"
if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
    SCREEGO_URL = sys.argv[1]

class CommSignals(QObject):
    state_updated = Signal(dict)

comm = CommSignals()

app_state = {"sharing": False, "paused": False}
pending_action = None

def run_audio_cmd(args):
    """Executes pactl commands directly or bridged through flatpak-spawn."""
    try:
        subprocess.run(args, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception:
        if shutil.which("flatpak-spawn"):
            try:
                subprocess.run(["flatpak-spawn", "--host"] + args, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except Exception:
                pass

def setup_virtual_mic():
    """Ensures the VirtualMic is created, unmuted, and active for the stream."""
    run_audio_cmd(["pactl", "load-module", "module-remap-source", "source_name=VirtualMic", "master=@DEFAULT_SINK@.monitor", "source_properties=device.description=VirtualMic"])
    run_audio_cmd(["pactl", "set-default-source", "VirtualMic"])
    run_audio_cmd(["pactl", "set-source-mute", "VirtualMic", "0"])
    run_audio_cmd(["pactl", "set-source-volume", "VirtualMic", "100%"])

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

def launch_hidden_browser(url):
    """Finds and launches Edge on your host computer system with full audio capture enabled."""
    setup_virtual_mic()
    executable_cmd = []

    # 1. Check if running inside Toolbx and bridge to Host Edge
    if shutil.which("flatpak-spawn"):
        for binary in ["microsoft-edge-stable", "microsoft-edge"]:
            res = subprocess.run(
                ["flatpak-spawn", "--host", "which", binary],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            if res.returncode == 0 and res.stdout.strip():
                executable_cmd = ["flatpak-spawn", "--host", res.stdout.strip()]
                break

        if not executable_cmd:
            res = subprocess.run(
                ["flatpak-spawn", "--host", "flatpak", "info", "com.microsoft.Edge"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            if res.returncode == 0:
                executable_cmd = ["flatpak-spawn", "--host", "flatpak", "run", "com.microsoft.Edge"]

    # 2. Check if running directly on Host
    if not executable_cmd:
        for binary in ["microsoft-edge-stable", "microsoft-edge"]:
            path = shutil.which(binary)
            if path:
                executable_cmd = [path]
                break

        if not executable_cmd and shutil.which("flatpak"):
            res = subprocess.run(
                ["flatpak", "info", "com.microsoft.Edge"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            if res.returncode == 0:
                executable_cmd = ["flatpak", "run", "com.microsoft.Edge"]

    if not executable_cmd:
        print("WARNING: Could not find Microsoft Edge on your computer system.")
        return None

    # Full audio + screen capture flags
    cmd = executable_cmd + [
        f"--app={url}",
        "--ozone-platform-hint=auto",
        "--enable-features=WebRTCPipeWireCapturer,VaapiVideoEncoder,VaapiVideoDecoder,CanvasOopRasterization,PulseaudioLoopbackForCast",
        "--alsa-input-device=pulse",
        "--alsa-output-device=pulse",
        "--use-fake-ui-for-media-stream",
        "--auto-select-desktop-capture-source=Entire screen",
        "--enable-usermedia-screen-capturing",
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--autoplay-policy=no-user-gesture-required",
        "--window-position=9999,9999",
        "--window-size=200,200",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-logging",
        "--log-level=3",
        "--disable-breakpad",
        "--disable-component-update"
    ]
    
    print(f"Launching Host Edge Streaming Engine with: {' '.join(executable_cmd)}")
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# Interactive indicator that supports clicking to collapse/expand and dragging to move
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
            if moved_dist < 6:  # Pure click, not a drag
                self.clicked.emit()
            self._drag_start_pos = None

    def mouseMoveEvent(self, event: QMouseEvent):
        self.window().mouseMoveEvent(event)


class OverlayToolbar(QWidget):
    def __init__(self):
        super().__init__()
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

        # Clickable indicator to collapse/expand
        self.indicator = InteractiveIndicator("●", self.container)
        self.indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.indicator.setToolTip("Click to collapse/expand toolbar")
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
        self.audio_muted = not self.audio_muted
        if self.audio_muted:
            self.btn_mute.setText("Unmute")
            self.btn_mute.setStyleSheet("background-color: #cc241d; color: white;")
            run_audio_cmd(["pactl", "set-source-mute", "VirtualMic", "1"])
        else:
            self.btn_mute.setText("Mute")
            self.btn_mute.setStyleSheet("")
            run_audio_cmd(["pactl", "set-source-mute", "VirtualMic", "0"])

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
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    browser_proc = launch_hidden_browser(SCREEGO_URL)

    app = QApplication(sys.argv)
    
    toolbar = OverlayToolbar()
    toolbar.show()
    
    def cleanup():
        if browser_proc:
            browser_proc.terminate()
            try:
                browser_proc.wait(timeout=2)
            except Exception:
                browser_proc.kill()
                
        # Safely unload VirtualMic from PipeWire
        run_audio_cmd(["pactl", "unload-module", "module-remap-source"])
        
        subprocess.run(["pkill", "-f", "go run . serve"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "screego"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "start.sh"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())