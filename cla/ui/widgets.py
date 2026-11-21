"""Reusable Qt widgets and helpers."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QPushButton, QWidget

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
IMAGES = ROOT / 'Images'
AUDIO = ROOT / 'Audio Clips'

BUTTON_CSS = ('QPushButton{background:#303035;border:1px solid #79654b;padding:9px 12px;} '
              'QPushButton:hover{background:#454047;} QPushButton:disabled{color:#77706a;border-color:#3d352b;}')
ACTION_CSS = ('QPushButton{background:#303035;color:#f4eebc;border:1px solid #79654b;border-radius:7px;'
              'padding:10px 16px;font:17px "Segoe UI";} QPushButton:hover{background:#454047;border-color:#b58a43;} '
              'QPushButton:pressed{background:#55443b;} QPushButton:disabled{color:#77706a;border-color:#3d352b;}')


def set_style(widget, css: str) -> None:
    """setStyleSheet forces a full re-polish; skip it when nothing changed."""
    if widget.property('_cla_css') != css:
        widget.setProperty('_cla_css', css)
        widget.setStyleSheet(css)


def to_qimage(arr) -> QImage:
    a = np.ascontiguousarray(arr)
    h, w = a.shape[:2]
    return QImage(a.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def physical_to_logical(rect):
    """Physical desktop rect (l, t, r, b) -> Qt logical QRect.

    Qt 6 keeps each screen's top-left at its native position and scales
    within the screen by devicePixelRatio. Identity at 100 % scaling.
    """
    left, top, right, bottom = (int(v) for v in rect)
    for screen in QGuiApplication.screens():
        g = screen.geometry()
        dpr = screen.devicePixelRatio()
        nw, nh = int(round(g.width() * dpr)), int(round(g.height() * dpr))
        if g.x() <= left < g.x() + nw and g.y() <= top < g.y() + nh:
            def lx(v):
                return g.x() + round((v - g.x()) / dpr)

            def ly(v):
                return g.y() + round((v - g.y()) / dpr)
            return QRect(lx(left), ly(top), max(1, lx(right) - lx(left)), max(1, ly(bottom) - ly(top)))
    return QRect(left, top, right - left, bottom - top)


class QtExecutor(QObject):
    """Runs work on a daemon thread; delivers callbacks on the GUI thread."""
    _deliver = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deliver.connect(self._on_deliver)

    def _on_deliver(self, callback, value):
        callback(value)

    def submit(self, fn, on_ok, on_err):
        def run():
            try:
                result = fn()
            except Exception as exc:      # delivered, never raised on the worker
                self._deliver.emit(on_err, exc)
            else:
                self._deliver.emit(on_ok, result)
        threading.Thread(target=run, daemon=True, name='CLA Calibration Capture').start()


class BannerStrip(QWidget):
    """Aspect-preserving image banner; scaled pixmap is cached per size."""

    def __init__(self, image, height, parent=None, optical_offset=0):
        super().__init__(parent)
        self.art = QPixmap(str(IMAGES / image))
        self.optical_offset = optical_offset
        self._scaled = None
        self._scaled_for = None
        self.setFixedHeight(height)
        self.setStyleSheet('background:transparent')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#050506'))
        if not self.art.isNull():
            size = (self.width(), self.height())
            if self._scaled_for != size:
                self._scaled = self.art.scaled(self.width(), self.height(), Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation)
                self._scaled_for = size
            x = (self.width() - self._scaled.width()) // 2 + self.optical_offset
            y = (self.height() - self._scaled.height()) // 2
            painter.drawPixmap(x, y, self._scaled)
        painter.end()


class MonitorOutline(QWidget):
    """Click-through frame OUTSIDE the captured region; no capture or polling."""

    def __init__(self):
        super().__init__(None)
        self.color = QColor('#35bf73')
        self.thickness = 10
        self._geometry_key = None
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def show_box(self, box, thickness=10, opacity=80, color='#e4b64d'):
        self.thickness = max(5, min(20, int(thickness)))
        self.setWindowOpacity(max(0.2, min(1.0, opacity / 100)))
        self.color = QColor(color)
        left, top, right, bottom = map(int, box)
        if right <= left or bottom <= top:
            self.hide()
            return
        r = physical_to_logical(box)
        pad = 6 + self.thickness   # every drawn pixel stays OUTSIDE dxcam's region
        key = (r.x(), r.y(), r.width(), r.height(), pad)
        if key != self._geometry_key:
            self.setGeometry(r.x() - pad, r.y() - pad, r.width() + 2 * pad, r.height() + 2 * pad)
            self._geometry_key = key
        self.update()
        if not self.isVisible():
            self.show()
            self._make_windows_click_through()

    def _make_windows_click_through(self):
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            user32.SetWindowLongW(hwnd, -20, user32.GetWindowLongW(hwnd, -20) | 0x20 | 0x80000 | 0x08000000)
        except Exception:
            pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(self.color, self.thickness))
        inset = self.thickness // 2 + 1
        painter.drawRect(self.rect().adjusted(inset, inset, -inset - 1, -inset - 1))
        painter.end()


class HotkeyButton(QPushButton):
    """Click, then press F1-F12 or a printable key. Never opens a dialog."""
    changed = Signal(str)
    rejected = Signal(str)
    # While any button is listening for a key (and briefly after), global
    # hotkeys are ignored so binding F8 doesn't also toggle monitoring.
    _guard_until = 0.0
    GUARD_S = 0.5

    @classmethod
    def capturing(cls) -> bool:
        return time.monotonic() < cls._guard_until

    def __init__(self, key: str, parent=None):
        super().__init__(key.upper(), parent)
        self._key = key.upper()
        self._binding = False
        self.clicked.connect(self._begin)

    def key(self) -> str:
        return self._key

    def set_key(self, key: str) -> None:
        if self._binding:
            HotkeyButton._guard_until = time.monotonic() + self.GUARD_S
        self._key = key.upper()
        self._binding = False
        self.setText(self._key)

    def _begin(self):
        self._binding = True
        HotkeyButton._guard_until = float('inf')
        self.setText('Press a key…')
        self.setFocus()

    def focusOutEvent(self, e):
        if self._binding:
            self.set_key(self._key)
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if not self._binding:
            return super().keyPressEvent(e)
        key = e.key()
        if key == Qt.Key_Escape:
            self.set_key(self._key)
            return
        fkeys = {getattr(Qt, f'Key_F{i}'): f'F{i}' for i in range(1, 13)}
        name = fkeys.get(key) or e.text().upper().strip()
        if not name or len(name) != 1 and name not in fkeys.values():
            self.rejected.emit('Choose F1–F12 or a printable key.')
            return
        self.set_key(name)
        self.changed.emit(name)
