"""Settings dialog. Validation errors are inline; no nested message boxes."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout

from .. import config as cfg
from .widgets import HotkeyButton


class Settings(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.app = parent
        c = parent.config
        self.setWindowTitle('CLA Settings')
        self.setMinimumWidth(370)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('Display/Hide stoplight outline'))
        self.overlay_hot = HotkeyButton(cfg.get(c, 'overlay_hotkey'))
        lay.addWidget(self.overlay_hot)
        lay.addWidget(QLabel('Monitor toggle hotkey'))
        self.hot = HotkeyButton(cfg.get(c, 'hotkey'))
        lay.addWidget(self.hot)
        lay.addWidget(QLabel('Calibration capture hotkey'))
        self.cap = HotkeyButton(cfg.get(c, 'capture_hotkey'))
        lay.addWidget(self.cap)
        for b in (self.overlay_hot, self.hot, self.cap):
            b.rejected.connect(self._show_error)
        lay.addWidget(QLabel('Outline thickness (pixels)'))
        self.overlay_width = QSpinBox()
        self.overlay_width.setRange(5, 20)
        self.overlay_width.setValue(int(cfg.get(c, 'overlay_width')))
        lay.addWidget(self.overlay_width)
        lay.addWidget(QLabel('Outline opacity'))
        self.overlay_opacity = QSlider(Qt.Horizontal)
        self.overlay_opacity.setRange(20, 100)
        self.overlay_opacity.setValue(int(cfg.get(c, 'overlay_opacity')))
        lay.addWidget(self.overlay_opacity)
        lay.addWidget(QLabel('Notification volume'))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(cfg.get(c, 'volume')))
        lay.addWidget(self.volume)
        self.error = QLabel('')
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color:#ff6b6b')
        lay.addWidget(self.error)
        done = QPushButton('Save Settings')
        done.clicked.connect(self.commit)
        lay.addWidget(done)

    def _show_error(self, text):
        self.error.setText(text)

    def commit(self):
        keys = {'hotkey': self.hot.key(), 'capture_hotkey': self.cap.key(),
                'overlay_hotkey': self.overlay_hot.key()}
        if len(set(keys.values())) != len(keys):
            self._show_error('All three hotkeys must be assigned different keys.')
            return
        c = self.app.config
        c.update(keys, volume=self.volume.value(), overlay_width=self.overlay_width.value(),
                 overlay_opacity=self.overlay_opacity.value())
        c.pop('overlay_enabled', None)
        cfg.save_config(c)
        self.app.install_hotkeys()
        self.app.refresh(force_outline=True)
        self.accept()
