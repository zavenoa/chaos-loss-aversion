"""CLA main window: thin Qt layer over the Qt-free core modules."""
from __future__ import annotations

import html
import random
import re
import sys
import webbrowser

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QTextBrowser, QVBoxLayout, QWidget)

from .. import VERSION
from .. import config as cfg
from ..calibration import CalibrationDeps, CalibrationSession
from ..hotkeys import HotkeyManager
from ..monitor import Monitor
from .settings import Settings
from .widgets import (ACTION_CSS, AUDIO, BUTTON_CSS, IMAGES, ROOT, BannerStrip, HotkeyButton,
                      MonitorOutline, QtExecutor, set_style, to_qimage)

GREEN = 'background:#186a3b;color:white;font-weight:bold;font-size:21px'
RED = 'background:#8d242b;color:white;font-weight:bold;font-size:21px'


class Bus(QObject):
    """Cross-thread signals. Worker/hook threads only ever emit these."""
    state = Signal(str)
    match = Signal(bool)
    error = Signal(str)
    toggle = Signal()
    capture = Signal()
    overlay_toggle = Signal()
    cal_cancel = Signal()


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = cfg.load_config()
        self._shutting_down = False
        self.bus = Bus()
        self.monitor = Monitor(self.bus.state.emit, self.bus.match.emit, self.bus.error.emit)
        self.hotkeys = HotkeyManager()
        self.session = CalibrationSession(self._cal_deps(), QtExecutor(self),
                                          cfg.get(self.config, 'capture_hotkey'),
                                          self.on_cal_view, self.on_cal_finished, self.on_cal_cancelled)
        self.audio_files = sorted(AUDIO.glob('*.mp3'))
        self.monitor_requested = False
        self.matched = False
        self.overlay_visible = True
        self.notice = ''
        self.notice_error = False

        b = self.bus
        guard = self._unless_binding
        b.state.connect(self.on_state)
        b.match.connect(self.on_match)
        b.error.connect(self.on_error)
        b.toggle.connect(guard(self.toggle))
        b.capture.connect(guard(self.session.capture))
        b.overlay_toggle.connect(guard(self.toggle_overlay))
        b.cal_cancel.connect(guard(self.session.cancel))

        self.outline = MonitorOutline()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.setWindowTitle(f'Chaos Loss Aversion | Version {VERSION}')
        self.setWindowIcon(QIcon(str(IMAGES / 'Chaos Orb.png')))
        self.resize(900, 960)
        self.setMinimumSize(730, 780)
        self.build_ui()
        self.install_hotkeys()
        self.refresh()

    # ================================================================ wiring
    @staticmethod
    def _unless_binding(fn):
        def slot():
            if not HotkeyButton.capturing():
                fn()
        return slot

    def _cal_deps(self):
        from .. import winapi
        from ..capture import capture_frame
        from ..detection import detect_slot_border, signature

        def capture(box):
            # Runs on the worker thread: wait for the monitor to release dxcam first.
            return capture_frame(box, before=lambda: self.monitor.wait_stopped(3.0))

        def detect(frame):
            import cv2
            return detect_slot_border(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY))

        return CalibrationDeps(cursor_pos=winapi.cursor_pos, capture_frame=capture,
                               detect_border=detect, build_signature=signature)

    def install_hotkeys(self):
        if self._shutting_down:
            return
        c = self.config
        b = self.bus
        try:
            self.hotkeys.clear()
            self.hotkeys.bind('toggle', cfg.get(c, 'hotkey'), b.toggle.emit)
            self.hotkeys.bind('capture', cfg.get(c, 'capture_hotkey'), b.capture.emit)
            self.hotkeys.bind('overlay', cfg.get(c, 'overlay_hotkey'), b.overlay_toggle.emit)
            if self.session.active:
                self.hotkeys.bind('cal_cancel', 'esc', b.cal_cancel.emit)
        except Exception as exc:
            self.set_notice(f'Hotkeys unavailable: {exc}', error=True)
        self.session.capture_key = str(cfg.get(c, 'capture_hotkey')).upper()

    # ================================================================ UI
    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet('QWidget{background:#050506;color:#f1e7d7;font:17px "Segoe UI"} '
                           'QPushButton{background:#222126;border:1px solid #79654b;border-radius:7px;'
                           'padding:10px;color:#f7ead6} QPushButton:hover{background:#3a3030} '
                           'QPushButton:disabled{color:#77706a;border-color:#3d352b} '
                           'QLabel{background:transparent}')
        lay = QVBoxLayout(root)
        lay.setContentsMargins(22, 12, 22, 12)
        lay.setSpacing(9)

        self.top_banner = BannerStrip('Chaos Loss Aversion Logo.png', 154)
        top = QHBoxLayout(self.top_banner)
        top.setContentsMargins(5, 8, 5, 8)
        self.cal_btn = QPushButton('  Calibrate')
        self.cal_btn.setIcon(QIcon(str(IMAGES / 'Calibrate Icon White.png')))
        self.cal_btn.setIconSize(QSize(16, 16))
        self.cal_btn.setStyleSheet(BUTTON_CSS)
        self.cal_btn.clicked.connect(self.start_calibration)
        top.addWidget(self.cal_btn, 0, Qt.AlignTop)
        top.addStretch(1)
        self.settings_btn = QPushButton('⚙ Settings')
        self.settings_btn.setStyleSheet(BUTTON_CSS)
        self.settings_btn.clicked.connect(self.settings)
        top.addWidget(self.settings_btn, 0, Qt.AlignTop)
        lay.addWidget(self.top_banner)

        note = QLabel('Only the center item slot in the Currency Tab is supported at this time.')
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet('color:#e8ba76;font-weight:bold;font-size:18px')
        lay.addWidget(note)

        self.panel = QWidget()
        self.panel.setStyleSheet('background:rgba(0,0,0,190);border:1px solid #594a36;border-radius:12px')
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(20, 20, 20, 20)
        panel.setSpacing(12)
        self.status = QLabel()
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        panel.addWidget(self.status, 1)
        # Dedicated, non-blocking instruction area for calibration.
        self.instructions = QLabel()
        self.instructions.setAlignment(Qt.AlignCenter)
        self.instructions.setWordWrap(True)
        self.instructions.setStyleSheet('font-size:17px;border:0')
        panel.addWidget(self.instructions)
        self.cal_error = QLabel()
        self.cal_error.setAlignment(Qt.AlignCenter)
        self.cal_error.setWordWrap(True)
        panel.addWidget(self.cal_error)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet('border:0')
        panel.addWidget(self.preview, 0)
        cal_row = QWidget()
        cal_row.setStyleSheet('border:0')
        row = QHBoxLayout(cal_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.no = QPushButton('No')
        self.yes = QPushButton('Yes')
        self.cancel_btn = QPushButton('Cancel Calibration (Esc)')
        for btn in (self.no, self.yes, self.cancel_btn):
            btn.setMinimumHeight(44)
            btn.setStyleSheet(ACTION_CSS)
            row.addWidget(btn)
        self.no.clicked.connect(lambda: self.session.answer(False))
        self.yes.clicked.connect(lambda: self.session.answer(True))
        self.cancel_btn.clicked.connect(self.session.cancel)
        panel.addWidget(cal_row)
        self.warning = QLabel('WARNING: Changing Display Mode or Resolution will require recalibration.')
        self.warning.setAlignment(Qt.AlignCenter)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet('color:#d6a77b;font-size:15px;border:0')
        panel.addWidget(self.warning)
        lay.addWidget(self.panel, 1)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setMinimumHeight(55)
        self.toggle_btn.clicked.connect(self.toggle)
        lay.addWidget(self.toggle_btn)

        self.poe_logo = QLabel()
        self.poe_logo.setAlignment(Qt.AlignCenter)
        art = QPixmap(str(IMAGES / 'PoE2 Logo.png'))
        if not art.isNull():
            self.poe_logo.setPixmap(art.scaled(220, 165, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.poe_logo.setMinimumHeight(115)
        lay.addWidget(self.poe_logo, 1)

        regex = QLabel('REGEX TOOLS')
        regex.setAlignment(Qt.AlignCenter)
        regex.setStyleSheet('color:#e8ba76;font-weight:bold;font-size:18px')
        lay.addWidget(regex)
        links = QHBoxLayout()
        for label, filename, url in [('Waystones', 'Waystone Icon.webp', 'https://poe2.re/waystone/'),
                                     ('Tablets', 'Tablet Icon.webp', 'https://poe2.re/tablet/'),
                                     ('Equipment', 'Renlys Tools Icon.svg', 'https://Renlys.Tools/')]:
            btn = QPushButton(label)
            btn.setIcon(QIcon(str(IMAGES / filename)))
            btn.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            links.addWidget(btn)
        lay.addLayout(links)
        db = QPushButton('PoE2DB  |  Modifiers')
        db.clicked.connect(lambda: webbrowser.open('https://poe2db.tw/us/Modifiers'))
        db.setIcon(QIcon(str(IMAGES / 'PoE2DB Icon.png')))
        db.setMinimumHeight(49)
        lay.addWidget(db)

        self.bottom_banner = BannerStrip('Tier Twolongs Banner.png', 226, optical_offset=-9)
        bottom = QHBoxLayout(self.bottom_banner)
        bottom.setContentsMargins(0, 0, 0, 2)
        version = QLabel(f'Version {VERSION}')
        version.setStyleSheet('color:#c8c8c8;font-size:14px;background:transparent')
        bottom.addWidget(version, 0, Qt.AlignBottom)
        bottom.addStretch(1)
        about = QPushButton('About')
        about.setStyleSheet('QPushButton{background:transparent;border:0;color:#c8c8c8;font-size:14px;'
                            'padding:2px 6px;} QPushButton:hover{color:#f4eebc;text-decoration:underline;}')
        about.clicked.connect(self.show_about)
        bottom.addWidget(about, 0, Qt.AlignBottom)
        lay.addWidget(self.bottom_banner)

    # ================================================================ refresh
    def set_notice(self, text, error=False):
        self.notice = text
        self.notice_error = error
        self.refresh()

    def refresh(self, force_outline=False):
        if self._shutting_down:
            return
        calibrating = self.session.active
        self.cal_btn.setEnabled(not calibrating)
        self.settings_btn.setEnabled(not calibrating)
        if calibrating:
            return            # on_cal_view owns the panel while calibrating
        profile = self.config.get('profile')
        active = self.monitor_requested
        self.update_outline(force=force_outline)
        for w in (self.no, self.yes, self.cancel_btn, self.preview):
            w.hide()
        self.warning.setVisible(bool(profile))
        self.toggle_btn.setVisible(bool(profile))
        hk = str(cfg.get(self.config, 'hotkey')).upper()
        self.toggle_btn.setText(f'{hk} to Stop' if active else f'{hk} to Monitor')
        set_style(self.toggle_btn, RED if active else GREEN)
        if not profile:
            status = 'Calibration Required!'
        elif not active:
            status = 'READY — NOT MONITORING'
        elif self.matched:
            status = 'MATCH DETECTED — MONITORING'
        else:
            status = 'MONITORING — NO MATCH'
        self.status.setText(status)
        set_style(self.status, 'font-size:32px;font-weight:bold;color:#ff5555;border:0' if not profile
                  else 'font-size:27px;font-weight:bold;color:#f1e7d7;border:0')
        self.instructions.setText(
            f'Press {str(cfg.get(self.config, "overlay_hotkey")).upper()} to show/hide the stoplight outline.'
            if profile else 'Click Calibrate to begin.')
        self.cal_error.setText(self.notice)
        set_style(self.cal_error, 'color:%s;font-size:16px;font-weight:bold;border:0'
                  % ('#ff6b6b' if self.notice_error else '#8fd19e'))
        self.cal_error.setVisible(bool(self.notice))

    def update_outline(self, force=False):
        profile = self.config.get('profile')
        if self.session.active or not profile or not self.overlay_visible:
            self.outline.hide()
            return
        color = '#e4b64d' if not self.monitor_requested else ('#c62828' if self.matched else '#35bf73')
        self.outline.show_box(profile['box'], int(cfg.get(self.config, 'overlay_width')),
                              int(cfg.get(self.config, 'overlay_opacity')), color=color)

    def toggle_overlay(self):
        if self._shutting_down:
            return
        self.overlay_visible = not self.overlay_visible
        self.update_outline(force=True)

    # ================================================================ calibration
    def start_calibration(self):
        if self._shutting_down or self.session.active:
            return
        self.monitor_requested = False
        self.matched = False
        self.monitor.stop()
        self.outline.hide()
        self.notice = ''
        self.session.capture_key = str(cfg.get(self.config, 'capture_hotkey')).upper()
        self.session.start()
        try:
            self.hotkeys.bind('cal_cancel', 'esc', self.bus.cal_cancel.emit)
        except Exception:
            pass          # Cancel button still works
        self.refresh()

    def on_cal_view(self, view):
        self.refresh()
        set_style(self.status, 'font-size:27px;font-weight:bold;color:#f1e7d7;border:0')
        self.status.setText(f'{view.title} — Step {view.step_no} of {view.total}')
        self.instructions.setText(view.text)
        self.cal_error.setText(view.error)
        set_style(self.cal_error, 'color:#ff6b6b;font-size:16px;font-weight:bold;border:0')
        self.cal_error.setVisible(bool(view.error))
        if view.preview is not None:
            pix = QPixmap.fromImage(to_qimage(view.preview)).scaled(250, 250, Qt.KeepAspectRatio,
                                                                     Qt.FastTransformation)
            self.preview.setPixmap(pix)
            self.preview.show()
        else:
            self.preview.hide()
        self.yes.setVisible(view.confirm)
        self.no.setVisible(view.confirm)
        self.cancel_btn.show()
        self.warning.hide()
        self.toggle_btn.hide()

    def _end_calibration_ui(self):
        self.hotkeys.unbind('cal_cancel')
        self.refresh(force_outline=True)

    def on_cal_finished(self, result):
        result['display'] = [(s.name(), s.geometry().getRect(), s.devicePixelRatio())
                             for s in QApplication.screens()]
        self.config['profile'] = result
        self.matched = False
        self.notice = (f'Calibration saved using {len(result["signature"]["points"])} border pixels. '
                       'Test detection before relying on it.')
        self.notice_error = False
        cfg.save_config(self.config)
        self._end_calibration_ui()

    def on_cal_cancelled(self):
        self.notice = 'Calibration cancelled. Previous calibration kept.'
        self.notice_error = False
        self._end_calibration_ui()

    # ================================================================ monitor
    def on_state(self, state):
        if self._shutting_down or self.session.active:
            return
        if state == 'NOT MONITORING' and self.monitor_requested and not self.monitor.running:
            # The capture thread exited unexpectedly. Don't leave a false green/red state.
            self.monitor_requested = False
            self.matched = False
        self.refresh()

    def on_match(self, is_matching):
        if self._shutting_down or not self.monitor_requested or self.session.active:
            return
        was = self.matched
        self.matched = is_matching
        if is_matching and not was and self.audio_files:
            self.audio.setVolume(int(cfg.get(self.config, 'volume')) / 100)
            self.player.setSource(QUrl.fromLocalFile(str(random.choice(self.audio_files))))
            self.player.play()
        self.refresh()

    def on_error(self, message):
        if self._shutting_down:
            return
        self.monitor_requested = False
        self.matched = False
        self.set_notice(f'Error: {message}', error=True)

    def toggle(self):
        if self._shutting_down or self.session.active:
            return
        if self.monitor_requested:
            self.monitor_requested = False
            self.monitor.stop()
            self.matched = False
            self.refresh()
            return
        profile = self.config.get('profile')
        if not profile:
            return
        if self.monitor.start(profile):
            self.notice = ''
            self.monitor_requested = True
            self.matched = False
            self.refresh()
        else:
            QTimer.singleShot(100, self._retry_start)   # previous thread still releasing dxcam

    def _retry_start(self):
        if not self._shutting_down and not self.monitor_requested and not self.session.active:
            self.toggle()

    # ================================================================ dialogs
    def settings(self):
        if not self.session.active:
            Settings(self).exec()

    def show_about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(f'About Chaos Loss Aversion — {VERSION}')
        dialog.resize(650, 550)
        dialog.setStyleSheet('QDialog{background:#101012;color:#e4d7a0;} QTextBrowser{background:#1b1919;'
                             'color:#e4d7a0;border:1px solid #956326;border-radius:7px;padding:14px;'
                             'font:14px "Segoe UI";} QPushButton{background:#303035;color:#f4eebc;'
                             'border:1px solid #956326;border-radius:6px;padding:8px 22px;}')
        layout = QVBoxLayout(dialog)
        heading = QLabel('CHAOS LOSS AVERSION')
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet('color:#d0b570;font-size:23px;font-weight:bold;')
        layout.addWidget(heading)
        body = QTextBrowser()
        try:
            content = (ROOT / 'README.txt').read_text(encoding='utf-8')
        except OSError:
            content = 'README not available.'

        def fmt(line):
            return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html.escape(line))
        lines = []
        for line in content.splitlines():
            if line.startswith('## '):
                lines.append('<h3 style="color:#d0b570;margin:16px 0 6px">' + fmt(line[3:]) + '</h3>')
            elif line.startswith('# '):
                lines.append('<h2 style="color:#f4eebc;margin:8px 0">' + fmt(line[2:]) + '</h2>')
            elif line.startswith('- '):
                lines.append('<div style="margin-left:14px">• ' + fmt(line[2:]) + '</div>')
            elif line.strip():
                lines.append('<div>' + fmt(line) + '</div>')
            else:
                lines.append('<div style="height:9px"></div>')
        body.setHtml('<div style="line-height:1.5;color:#e4d7a0">' + ''.join(lines) + '</div>')
        layout.addWidget(body)
        close = QPushButton('Close')
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignRight)
        dialog.exec()

    # ================================================================ shutdown
    def shutdown(self):
        """Release all global resources before letting Qt terminate."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.monitor_requested = False
        self.monitor.stop()
        try:
            self.session.cancel()
        except Exception:
            pass
        try:
            self.hotkeys.clear()
        except Exception:
            pass
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except Exception:
            pass
        self.monitor.stop(wait=True, timeout=2.5)
        try:
            self.outline.hide()
            self.outline.close()
            self.outline.deleteLater()
        except Exception:
            pass

    def closeEvent(self, e):
        self.shutdown()
        e.accept()
        QApplication.instance().quit()


def run():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(IMAGES / 'Chaos Orb.png')))
    app.setQuitOnLastWindowClosed(True)
    window = Main()
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()
