# /home/test/Documents/server/control_server.py
import sys
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
import threading

# PySide6 Imports
from PySide6.QtCore import Qt, QPoint, Signal, QObject
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QPushButton, QLabel, QGraphicsDropShadowEffect
from PySide6.QtGui import QColor

PORT = 5055

# Thread-safe communicator between HTTP thread and Qt Thread
class CommSignals(QObject):
    state_updated = Signal(dict)

comm = CommSignals()

# Global states
pending_action = None
app_state = {"sharing": False, "paused": False}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress console spam

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def do_GET(self):
        global pending_action
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()

        if self.path == '/toggle':
            pending_action = "toggle_pause"
            self.wfile.write(b'{"status": "ok"}')
        elif self.path == '/poll':
            if pending_action:
                self.wfile.write(json.dumps({"action": pending_action}).encode())
                pending_action = None
            else:
                self.wfile.write(b'{"action": "none"}')

    def do_POST(self):
        global app_state
        if self.path == '/state':
            content_length = int(self.headers['Content-Length'])
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

# PySide6 Overlay Window
class OverlayToolbar(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        # Frameless, transparent, stays on top of all windows
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Main Layout
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        # Style container (Gruvbox themed)
        self.container = QWidget(self)
        self.container.setObjectName("Container")
        self.container.setStyleSheet("""
            QWidget#Container {
                background-color: rgba(40, 40, 40, 220);
                border: 1px solid #458588;
                border-radius: 18px;
            }
            QPushButton {
                background-color: #3c3836;
                color: #fbf1c7;
                border: none;
                border-radius: 12px;
                padding: 6px 14px;
                font-size: 12px;
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
            QLabel {
                color: #a89984;
                font-family: sans-serif;
                font-size: 13px;
                font-weight: bold;
            }
        """)

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(8, 4, 8, 4)
        container_layout.setSpacing(6)

        # Drag grip
        self.grip = QLabel(" ⠿ ", self.container)
        self.grip.setCursor(Qt.CursorShape.OpenHandCursor)
        container_layout.addWidget(self.grip)

        # Share Button
        self.btn_share = QPushButton("Share", self.container)
        self.btn_share.clicked.connect(self.toggle_share)
        container_layout.addWidget(self.btn_share)

        # Pause Button
        self.btn_pause = QPushButton("Pause", self.container)
        self.btn_pause.clicked.connect(self.trigger_pause)
        self.btn_pause.setEnabled(False)
        container_layout.addWidget(self.btn_pause)

        # Status / Indicator light
        self.indicator = QLabel("● Ready", self.container)
        self.indicator.setStyleSheet("color: #b8bb26;") # Green for ready
        container_layout.addWidget(self.indicator)

        layout.addWidget(self.container)
        self.setLayout(layout)

        # Shadow effect for better contrast over bright slides
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)

        # Connect the state signal
        comm.state_updated.connect(self.update_gui_state)

        # Default size and position (top center of the screen)
        self.resize(320, 50)
        self.move(20, 80)

    def toggle_share(self):
        global pending_action
        if app_state["sharing"]:
            pending_action = "stop_share"
        else:
            pending_action = "start_share"

    def trigger_pause(self):
        global pending_action
        pending_action = "toggle_pause"

    def update_gui_state(self, state):
        if state["sharing"]:
            self.btn_share.setText("Stop")
            self.btn_share.setStyleSheet("background-color: #cc241d; color: white;") # Red for stop
            self.btn_pause.setEnabled(True)
            if state["paused"]:
                self.btn_pause.setText("Resume")
                self.btn_pause.setStyleSheet("background-color: #fabd2f; color: black;") # Yellow for paused
                self.indicator.setText("● Paused")
                self.indicator.setStyleSheet("color: #fabd2f;")
            else:
                self.btn_pause.setText("Pause")
                self.btn_pause.setStyleSheet("")
                self.indicator.setText("● Live")
                self.indicator.setStyleSheet("color: #fe8019;") # Orange for live
        else:
            self.btn_share.setText("Share")
            self.btn_share.setStyleSheet("")
            self.btn_pause.setText("Pause")
            self.btn_pause.setStyleSheet("")
            self.btn_pause.setEnabled(False)
            self.indicator.setText("● Ready")
            self.indicator.setStyleSheet("color: #b8bb26;")

    # Wayland & X11 Native Dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.windowHandle()
            if window:
                window.startSystemMove()
            event.accept()

if __name__ == '__main__':
    # Start HTTP Server in background thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Start PySide6 Application on main thread
    app = QApplication(sys.argv)
    toolbar = OverlayToolbar()
    toolbar.show()
    sys.exit(app.exec())