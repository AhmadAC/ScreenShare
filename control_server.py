# Control_server.py
import os
import sys
import time
import threading

# Allow Qt to use xcb fallback on Wayland for 100% overlay compatibility on Linux
if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"

from PySide6.QtWidgets import QApplication

from system_util import (
    log, EXECUTION_DIR, LOG_FILE_PATH,
    detect_lan_ip, write_link_file, kill_port_owners,
    setup_pipewire_audio, setup_windows_audio, cleanup_audio, sync_audio_volume,
    set_physical_mics_muted
)
from server_builder import (
    start_screenshare_server, wait_for_server, launch_hidden_browser
)
from bridge_server import run_http_server, PORT
from gui_overlay import OverlayToolbar

ROOM_NAME = "a"

class ScreenShareHostFacade:
    """Unified facade coordinating server compilation, browser launch, bridge HTTP server, and GUI."""
    def __init__(self, room_name=ROOM_NAME, bridge_port=PORT):
        self.room_name = room_name
        self.bridge_port = bridge_port
        self.lan_ip = "127.0.0.1"
        self.viewer_url = ""
        self.server_proc = None
        self.browser_proc = None
        self.toolbar = None
        self.app = None

    def start(self):
        log("=================================================================")
        log(" ScreenShare Host Starting")
        log(f" Execution Working Dir : {EXECUTION_DIR}")
        log(f" Log File Location     : {LOG_FILE_PATH}")
        log(f" Python sys.executable : {sys.executable}")
        log(f" Frozen bundle status  : {getattr(sys, 'frozen', False)}")
        log("=================================================================")

        kill_port_owners()
        time.sleep(0.5)

        self.lan_ip = detect_lan_ip()
        self.viewer_url = f"http://{self.lan_ip}:5050/?room={self.room_name}&create=true"
        log(f" Detected Local IP     : {self.lan_ip}")
        log(f" Viewers URL           : http://{self.lan_ip}:5050")

        write_link_file(f"http://{self.lan_ip}:5050/?room={self.room_name}")
        setup_pipewire_audio()
        setup_windows_audio()
        set_physical_mics_muted(True)

        # 1. Start Go Server
        self.server_proc = start_screenshare_server(self.lan_ip)
        server_healthy = wait_for_server("http://127.0.0.1:5050/health", proc=self.server_proc, timeout=6.0)
        if not server_healthy:
            log("ERROR: ScreenShare backend server failed to initialize or terminated prematurely.")

        # 2. Start HTTP Bridge & Audio Synchronization
        http_thread = threading.Thread(target=run_http_server, args=(self.bridge_port,), daemon=True)
        http_thread.start()
        log(f"Local control bridge HTTP server listening on 127.0.0.1:{self.bridge_port}")

        sync_thread = threading.Thread(target=sync_audio_volume, daemon=True)
        sync_thread.start()
        log("Audio sync thread started (mirroring sink volume to Computer Sound)")

        # 3. Launch Hidden Chromium/Edge Browser
        room_url = f"http://127.0.0.1:5050/?room={self.room_name}&create=true"
        self.browser_proc = launch_hidden_browser(room_url)

        # 4. Initialize Overlay GUI
        self.app = QApplication(sys.argv)
        self.toolbar = OverlayToolbar(self.lan_ip, self.room_name)
        self.toolbar.show()
        self.app.aboutToQuit.connect(self.cleanup)

    def cleanup(self):
        log("Application shutdown initiated. Cleaning up subprocesses...")
        if self.toolbar and self.toolbar.qr_dialog:
            self.toolbar.qr_dialog.close()

        if self.browser_proc:
            self.browser_proc.terminate()
            try:
                self.browser_proc.wait(timeout=2)
            except Exception:
                self.browser_proc.kill()

        if self.server_proc:
            self.server_proc.terminate()
            try:
                self.server_proc.wait(timeout=2)
            except Exception:
                self.server_proc.kill()

        cleanup_audio()
        log("Cleanup finished. ScreenShare Host terminated.")

    def run(self):
        self.start()
        sys.exit(self.app.exec())

if __name__ == '__main__':
    facade = ScreenShareHostFacade()
    facade.run()