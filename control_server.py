# /home/test/Documents/server/control_server.py
import sys
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

# PySide6 Imports for Overlay Toolbar
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QPushButton, QLabel, 
    QGraphicsDropShadowEffect, QSizePolicy
)
from PySide6.QtGui import QColor

PORT = 5055

# Check if a URL was passed via command line arguments from start.sh
SCREEGO_URL = "http://127.0.0.1:5050/?room=a&create=true"
if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
    SCREEGO_URL = sys.argv[1]

# Thread-safe communicator between HTTP thread and Qt Thread
class CommSignals(QObject):
    state_updated = Signal(dict)

comm = CommSignals()

# Global states
app_state = {"sharing": False, "paused": False}
pending_action = None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress console spam

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

def rehide_browser_window():
    """Aggressively moves and lowers the browser window off-screen if KDE tries to bring it to focus."""
    for _ in range(15):  # Check every 200ms for 3 seconds
        try:
            subprocess.run(
                ["xdotool", "search", "--name", "Screego", "windowmove", "9999", "9999"],
                stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
            )
            subprocess.run(
                ["wmctrl", "-r", "Screego", "-b", "add,below,skip_taskbar,skip_pager"],
                stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
            )
            subprocess.run(
                ["xdotool", "search", "--name", "Screego", "windowminimize"],
                stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
            )
        except Exception:
            pass
        time.sleep(0.2)

def launch_hidden_browser(url):
    """Finds Edge or Chrome and launches it completely hidden off-screen in the background."""
    browsers = [
        "microsoft-edge-stable", "microsoft-edge",
        "google-chrome-stable", "google-chrome",
        "chromium-browser", "chromium"
    ]
    
    executable = None
    for b in browsers:
        path = shutil.which(b)
        if path:
            executable = path
            break
            
    if not executable:
        print("WARNING: No Edge or Chrome executable found.")
        return None

    cmd = [
        executable,
        f"--app={url}",
        "--use-fake-ui-for-media-stream",
        "--auto-select-desktop-capture-source=Entire screen",
        "--enable-usermedia-screen-capturing",
        "--enable-features=WebRTCPipeWireCapturer,VaapiVideoEncoder,VaapiVideoDecoder,CanvasOopRasterization",
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
    
    print(f"Launching Background Streaming Engine...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=rehide_browser_window, daemon=True).start()
    return proc


# PySide6 Overlay Window
class OverlayToolbar(QWidget):
    def __init__(self):
        super().__init__()
        self.audio_muted = False
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetFixedSize)

        self.container = QWidget(self)
        self.container.setObjectName("Container")
        self.container.setStyleSheet("""
            QWidget#Container {
                background-color: rgba(40, 40, 40, 220);
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
        self.grip.setCursor(Qt.CursorShape.OpenHandCursor)
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

        self.indicator = QLabel("●", self.container)
        self.indicator.setStyleSheet("color: #b8bb26;")
        container_layout.addWidget(self.indicator)
        
        # Add Exit Button to clean up and quit
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
        self.move(20, 80)

    def toggle_share(self):
        global pending_action
        if app_state["sharing"]:
            pending_action = "stop_share"
        else:
            pending_action = "start_share"
            threading.Thread(target=rehide_browser_window, daemon=True).start()

    def trigger_pause(self):
        global pending_action
        pending_action = "toggle_pause"

    def toggle_mute(self):
        self.audio_muted = not self.audio_muted
        if self.audio_muted:
            self.btn_mute.setText("Unmute")
            self.btn_mute.setStyleSheet("background-color: #cc241d; color: white;")
            subprocess.run(["pactl", "set-source-mute", "VirtualMic", "1"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        else:
            self.btn_mute.setText("Mute")
            self.btn_mute.setStyleSheet("")
            subprocess.run(["pactl", "set-source-mute", "VirtualMic", "0"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

    def update_gui_state(self, state):
        if state["sharing"]:
            self.btn_share.setText("Stop")
            self.btn_share.setStyleSheet("background-color: #cc241d; color: white;")
            self.btn_pause.setEnabled(True)
            if state["paused"]:
                self.btn_pause.setText("Resume")
                self.btn_pause.setStyleSheet("background-color: #fabd2f; color: black;")
                self.indicator.setStyleSheet("color: #fabd2f;") # Yellow indicator
            else:
                self.btn_pause.setText("Pause")
                self.btn_pause.setStyleSheet("")
                self.indicator.setStyleSheet("color: #fe8019;") # Orange indicator
        else:
            self.btn_share.setText("Share")
            self.btn_share.setStyleSheet("")
            self.btn_pause.setText("Pause")
            self.btn_pause.setStyleSheet("")
            self.btn_pause.setEnabled(False)
            self.indicator.setStyleSheet("color: #b8bb26;") # Green indicator

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.windowHandle()
            if window:
                window.startSystemMove()
            event.accept()

if __name__ == '__main__':
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    browser_proc = launch_hidden_browser(SCREEGO_URL)

    app = QApplication(sys.argv)
    
    toolbar = OverlayToolbar()
    toolbar.show()
    
    def cleanup():
        # 1. Kill hidden browser stream
        if browser_proc:
            browser_proc.terminate()
            try:
                browser_proc.wait(timeout=2)
            except Exception:
                browser_proc.kill()
                
        # 2. Delete Virtual Microphone from Linux PulseAudio/PipeWire
        subprocess.run(["pactl", "unload-module", "module-remap-source"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        
        # 3. Kill the Go server running in start.sh
        subprocess.run(["pkill", "-f", "go run . serve"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "screego"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        
        # 4. Kill the bash script itself
        subprocess.run(["pkill", "-f", "start.sh"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())