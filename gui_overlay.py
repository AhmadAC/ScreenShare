import sys
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, 
    QGraphicsDropShadowEffect
)
from PySide6.QtGui import QColor, QMouseEvent
from qr_util import get_qr_pixmap
from bridge_server import comm, get_app_state, set_pending_action, update_app_state
from system_util import run_audio_cmd, set_physical_mics_muted, get_active_audio_source

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
    def __init__(self, lan_ip, room_name="a"):
        super().__init__()
        self.lan_ip = lan_ip
        self.viewer_url = f"http://{self.lan_ip}:5050/?room={room_name}&create=true"
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

        self.btn_sound = QPushButton("Computer Sound", self.container)
        self.btn_sound.clicked.connect(self.toggle_sound)
        container_layout.addWidget(self.btn_sound)

        self.btn_mic = QPushButton("Mic: On", self.container)
        self.btn_mic.clicked.connect(self.toggle_mic)
        container_layout.addWidget(self.btn_mic)

        self.btn_qr = QPushButton("QR", self.container)
        self.btn_qr.setObjectName("QRBtn")
        self.btn_qr.setToolTip("Show QR code for phone scan")
        self.btn_qr.clicked.connect(self.toggle_qr)
        container_layout.addWidget(self.btn_qr)

        self.indicator = InteractiveIndicator("●", self.container)
        self.indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.indicator.setToolTip(f"ScreenShare running on {self.viewer_url}\nLink written to link.txt\nClick to collapse/expand")
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
        self.btn_sound.setVisible(not self.is_collapsed)
        self.btn_mic.setVisible(not self.is_collapsed)
        self.btn_qr.setVisible(not self.is_collapsed)
        self.btn_exit.setVisible(not self.is_collapsed)
        if self.is_collapsed and self.qr_dialog.isVisible():
            self.qr_dialog.hide()
        self.container.adjustSize()
        self.adjustSize()

    def toggle_share(self):
        is_sharing = get_app_state().get("sharing", False)
        if is_sharing:
            self.btn_share.setText("Stopping...")
            set_pending_action("stop_share")
        else:
            self.btn_share.setText("Starting...")
            set_pending_action("start_share")

    def trigger_pause(self):
        set_pending_action("toggle_pause")

    def toggle_sound(self):
        current_muted = get_app_state().get("soundMuted", False)
        new_muted = not current_muted
        update_app_state({"soundMuted": new_muted})
        set_pending_action("toggle_sound")
        self.update_gui_state(get_app_state())
        if sys.platform.startswith("linux"):
            source = get_active_audio_source()
            run_audio_cmd(["pactl", "set-source-mute", source, "1" if new_muted else "0"])

    def toggle_mic(self):
        current_mic_muted = get_app_state().get("micMuted", False)
        new_mic_muted = not current_mic_muted
        update_app_state({"micMuted": new_mic_muted})
        set_pending_action("toggle_mic")
        self.update_gui_state(get_app_state())
        set_physical_mics_muted(new_mic_muted)

    def update_gui_state(self, state):
        if state.get("sharing", False):
            self.btn_share.setText("Stop")
            self.btn_share.setStyleSheet("background-color: #cc241d; color: white;")
            self.btn_pause.setEnabled(True)
            if state.get("paused", False):
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

        if state.get("soundMuted", False):
            self.btn_sound.setText("Sound Muted")
            self.btn_sound.setStyleSheet("background-color: #cc241d; color: white;")
        else:
            self.btn_sound.setText("Computer Sound")
            self.btn_sound.setStyleSheet("")

        mic_is_muted = state.get("micMuted", False)
        if mic_is_muted:
            self.btn_mic.setText("Mic: Off")
            self.btn_mic.setStyleSheet("background-color: #cc241d; color: white;")
        else:
            self.btn_mic.setText("Mic: On")
            self.btn_mic.setStyleSheet("")

        set_physical_mics_muted(mic_is_muted)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()