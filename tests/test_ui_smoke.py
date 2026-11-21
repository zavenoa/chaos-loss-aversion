"""End-to-end wiring of the real Main window with fake capture/hotkey backends.

Uses tests/qtstub.py only when PySide6 is unavailable (e.g. Linux). With real
PySide6 installed this test is skipped; run the app manually instead.
"""
import importlib

import numpy as np
import pytest

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

pytestmark = pytest.mark.skipif(HAVE_QT, reason='uses the headless Qt stub')

from conftest import wait_until  # noqa: E402
from test_core import FakeKb, _border_pair  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    import qtstub
    qtstub.install()
    import cla.config as cfg
    import cla.hotkeys as hk
    import cla.winapi as wa
    import cla.capture as cap
    import cla.detection as det
    monkeypatch.setattr(cfg, 'CONFIG', tmp_path / 'config.json')
    kb = FakeKb()
    monkeypatch.setattr(hk, '_KeyboardLib', lambda: kb)
    cursor, frames = [], []
    monkeypatch.setattr(wa, 'cursor_pos', lambda: cursor.pop(0))
    monkeypatch.setattr(cap, 'capture_frame', lambda box, before=None: (before and before(), frames.pop(0))[1])
    monkeypatch.setattr(det, 'detect_slot_border', lambda gray: (1, 1, 58, 60))
    import cla.ui.widgets
    import cla.ui.settings
    import cla.ui.app as appmod
    importlib.reload(cla.ui.widgets)
    importlib.reload(cla.ui.settings)
    importlib.reload(appmod)
    # Deterministic captures here; the threaded path is covered in test_calibration.py.
    from cla.calibration import SyncExecutor
    monkeypatch.setattr(appmod, 'QtExecutor', lambda parent=None: SyncExecutor())
    main = appmod.Main()
    ns = type('NS', (), {})()
    ns.main, ns.kb, ns.cursor, ns.frames, ns.cfg = main, kb, cursor, frames, cfg
    ns.neg, ns.pos = _border_pair(4, 60, 58)
    yield ns
    main.shutdown()


def press(kb, key):
    kb.down(key)
    kb.up(key)


def test_initial_state_requires_calibration(app):
    m = app.main
    assert m.status.text() == 'Calibration Required!'
    assert not m.toggle_btn.isVisible()
    for name in ('toggle', 'capture', 'overlay'):
        assert m.hotkeys.bound(name)
    assert not m.hotkeys.bound('cal_cancel')


def test_calibration_inline_complete(app):
    m, kb = app.main, app.kb
    m.cal_btn.click()
    assert m.session.active and m.cancel_btn.isVisible() and not m.cal_btn.isEnabled()
    assert not m.settings_btn.isEnabled() and m.hotkeys.bound('cal_cancel')
    assert 'Step 1 of 5' in m.status.text()
    app.cursor += [(100, 100), (160, 162)]
    app.frames += [np.zeros((63, 61, 3), np.uint8), app.neg, app.pos]
    press(kb, 'f9')
    press(kb, 'f9')
    assert wait_until(lambda: m.session.step == 'confirm', 3)
    assert m.yes.isVisible() and m.no.isVisible() and m.preview.isVisible()
    m.yes.click()
    press(kb, 'f9')
    assert wait_until(lambda: m.session.step == 'pos', 3)
    press(kb, 'f9')
    assert wait_until(lambda: not m.session.active, 3)
    assert 'Calibration saved' in m.cal_error.text()
    assert app.cfg.load_config()['profile']['box'] == [101, 101, 159, 161]
    assert m.cal_btn.isEnabled() and not m.hotkeys.bound('cal_cancel')
    assert m.toggle_btn.isVisible() and m.status.text() == 'READY — NOT MONITORING'


def test_cancel_and_restart_repeatedly(app):
    m, kb = app.main, app.kb
    for i in range(100):
        m.cal_btn.click()
        assert m.session.active and m.hotkeys.bound('cal_cancel')
        if i % 2:
            app.cursor.append((5, 5))
            press(kb, 'f9')                     # partway through
        if i % 3 == 0:
            m.cancel_btn.click()
        else:
            press(kb, 'esc')
        assert not m.session.active
        assert not m.hotkeys.bound('cal_cancel'), 'ESC hook leaked after cancel'
        assert m.cal_btn.isEnabled() and m.settings_btn.isEnabled()
        assert 'cancelled' in m.cal_error.text()
    for name in ('toggle', 'capture', 'overlay'):
        assert m.hotkeys.bound(name)


def test_hotkeys_ignored_while_binding_a_key(app):
    m, kb = app.main, app.kb
    from cla.ui.widgets import HotkeyButton
    m.cal_btn.click()
    button = HotkeyButton('F9')
    button.click()
    assert HotkeyButton.capturing()
    app.cursor.append((5, 5))
    press(kb, 'f9')
    assert m.session.step == 'ul' and app.cursor == [(5, 5)]
    button.set_key('F9')
    HotkeyButton._guard_until = 0.0
    m.session.cancel()


def test_shutdown_releases_everything(app):
    m = app.main
    m.cal_btn.click()
    m.shutdown()
    assert not m.session.active
    assert not any(m.hotkeys.bound(n) for n in ('toggle', 'capture', 'overlay', 'cal_cancel'))


def test_app_icon_and_taskbar_identity(app):
    import cla.ui.app as appmod
    assert appmod.APP_USER_MODEL_ID == 'TierTwolongs.ChaosLossAversion'
    assert appmod.app_icon() is not None
