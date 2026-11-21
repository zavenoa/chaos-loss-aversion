"""Detection, monitor, hotkeys, config and the no-input guarantee."""
import re
import time
from pathlib import Path

import numpy as np
import pytest

import legacy_signature
from conftest import wait_until
from cla.config import load_config, save_config
from cla.detection import MatchDetector, signature
from cla.hotkeys import HotkeyManager
from cla.monitor import Monitor

PKG = Path(__file__).resolve().parents[1] / 'cla'


# ------------------------------------------------------------------ public CLA never sends input
def test_cla_contains_no_input_injection():
    banned = re.compile(r'SendInput|mouse_event|keybd_event|SetCursorPos|SetPhysicalCursorPos|'
                        r'keyboard\.(press|release|send|write)|pyautogui|pynput')
    hits = [f'{p.relative_to(PKG.parent)}:{i}' for p in PKG.rglob('*.py')
            for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1)
            if banned.search(line) and not line.lstrip().startswith('#')]
    assert hits == [], f'input injection found: {hits}'


# ------------------------------------------------------------------ hotkeys
class FakeKb:
    def __init__(self):
        self.press, self.release = {}, {}

    def on_press_key(self, key, cb):
        self.press.setdefault(key, []).append(cb)
        return ('p', key, cb)

    def on_release_key(self, key, cb):
        self.release.setdefault(key, []).append(cb)
        return ('r', key, cb)

    def unhook(self, h):
        (self.press if h[0] == 'p' else self.release)[h[1]].remove(h[2])

    def down(self, key):
        for cb in list(self.press.get(key, [])):
            cb(None)

    def up(self, key):
        for cb in list(self.release.get(key, [])):
            cb(None)


def test_hotkey_fires_once_per_physical_press():
    kb, t = FakeKb(), [0.0]
    hm = HotkeyManager(kb, clock=lambda: t[0])
    hits = []
    hm.bind('toggle', 'F8', lambda: hits.append(1))
    kb.down('f8'); t[0] += .03; kb.down('f8'); t[0] += .03; kb.down('f8')   # auto-repeat
    assert hits == [1]
    kb.up('f8'); kb.down('f8')
    assert hits == [1, 1]


def test_hotkey_recovers_from_missed_keyup():
    kb, t = FakeKb(), [0.0]
    hm = HotkeyManager(kb, clock=lambda: t[0])
    hits = []
    hm.bind('toggle', 'f8', lambda: hits.append(1))
    kb.down('f8'); t[0] += 5.0; kb.down('f8')
    assert hits == [1, 1]


def test_hotkey_rebind_and_clear():
    kb = FakeKb()
    hm = HotkeyManager(kb)
    hits = []
    hm.bind('a', 'f8', lambda: hits.append('a'))
    hm.bind('a', 'f9', lambda: hits.append('b'))
    kb.down('f8'); kb.down('f9')
    assert hits == ['b']
    hm.clear()
    kb.up('f9'); kb.down('f9')
    assert hits == ['b'] and not any(kb.press.values())


# ------------------------------------------------------------------ detection
def _border_pair(seed=0, h=60, w=58):
    rng = np.random.default_rng(seed)
    neg = rng.integers(0, 40, (h, w, 3), dtype=np.uint8)
    pos = neg.copy()
    band = max(3, min(h, w) // 9)
    pos[int(h * .55):, :band] = (230, 190, 90)
    pos[int(h * .55):, -band:] = (230, 190, 90)
    pos[-band:, :] = (230, 190, 90)
    pos += rng.integers(0, 6, pos.shape, dtype=np.uint8)
    return neg, pos


def _unique_diff_pair(seed, size=30):
    """Every candidate pixel gets a distinct contrast value, so ordering is unambiguous."""
    rng = np.random.default_rng(seed)
    neg = np.zeros((size, size, 3), np.uint8)
    pos = neg.copy()
    values = rng.permutation(np.arange(35, 256))
    band = max(3, size // 9)
    k = 0
    for y in range(size):
        for x in range(size):
            if y >= int(size * .55) and (x < band or x >= size - band or y >= size - band):
                pos[y, x, 0] = values[k]
                k += 1
    return neg, pos


@pytest.mark.parametrize('seed', range(8))
def test_signature_identical_to_legacy_when_unambiguous(seed):
    neg, pos = _unique_diff_pair(seed)
    assert signature(neg, pos) == legacy_signature.signature(neg, pos)


@pytest.mark.parametrize('seed', range(6))
def test_signature_properties_on_noisy_border(seed):
    neg, pos = _border_pair(seed, 55 + seed, 50 + 2 * seed)
    new, old = signature(neg, pos), legacy_signature.signature(neg, pos)
    h, w = neg.shape[:2]
    diff = np.abs(neg.astype(int) - pos.astype(int)).max(axis=2)
    spacing = max(3, min(h, w) // 24)
    pts = new['points']
    assert 4 <= len(pts) <= 24 and abs(len(pts) - len(old['points'])) <= 2
    assert diff[pts[0][1], pts[0][0]] == max(diff[y, x] for x, y in old['points'])
    for i, (x, y) in enumerate(pts):
        assert y >= int(h * .55) and 2 <= x < w - 2 and 2 <= y < h - 2 and diff[y, x] >= 35
        for px, py in pts[:i]:
            assert (x - px) ** 2 + (y - py) ** 2 >= spacing ** 2


def test_signature_faster_than_legacy():
    neg, pos = _border_pair(1, 300, 300)
    t0 = time.perf_counter(); legacy_signature.signature(neg, pos); legacy = time.perf_counter() - t0
    t0 = time.perf_counter(); signature(neg, pos); new = time.perf_counter() - t0
    assert new < legacy


def test_detector_classifies():
    neg, pos = _border_pair(2)
    det = MatchDetector(signature(neg, pos))
    assert det.classify(pos) == (True, False)
    assert det.classify(neg) == (False, True)
    with pytest.raises(ValueError):
        MatchDetector({'region': 'old', 'points': [], 'positive': [], 'negative': []})


# ------------------------------------------------------------------ monitor
class FakeCam:
    def __init__(self, frames):
        self.frames = frames
        self.released = False

    def grab(self, region=None):
        time.sleep(0.001)
        return self.frames()

    def release(self):
        self.released = True


class FakePoll:
    down = False
    pos = (0, 0)

    def left_down(self):
        return FakePoll.down

    def cursor(self):
        return FakePoll.pos


def test_monitor_latch_and_click_clear():
    neg, pos = _border_pair(3)
    profile = {'box': [100, 100, 158, 160], 'signature': signature(neg, pos)}
    current = {'f': neg}
    events = []
    cam = FakeCam(lambda: current['f'])
    mon = Monitor(lambda s: events.append(('state', s)), lambda m: events.append(('match', m)),
                  lambda e: events.append(('err', e)), camera_factory=lambda: cam, poll_factory=FakePoll)
    assert mon.start(profile) and mon.start(profile) is False
    assert wait_until(lambda: ('state', 'MONITORING') in events)
    current['f'] = pos
    assert wait_until(lambda: ('match', True) in events)
    time.sleep(0.05)
    assert events.count(('match', True)) == 1              # latched, not re-fired
    FakePoll.pos = (120, 130); FakePoll.down = True         # click inside slot clears
    assert wait_until(lambda: ('match', False) in events)
    FakePoll.down = False
    current['f'] = neg
    time.sleep(0.05)
    current['f'] = pos
    assert wait_until(lambda: events.count(('match', True)) == 2)
    assert mon.stop(wait=True)
    assert cam.released and events[-1] == ('state', 'NOT MONITORING')
    assert not any(e[0] == 'err' for e in events)


def test_click_outside_slot_does_not_clear():
    neg, pos = _border_pair(5)
    profile = {'box': [100, 100, 158, 160], 'signature': signature(neg, pos)}
    events = []
    FakePoll.down, FakePoll.pos = False, (0, 0)
    mon = Monitor(lambda s: None, lambda m: events.append(m), lambda e: events.append(e),
                  camera_factory=lambda: FakeCam(lambda: pos), poll_factory=FakePoll)
    mon.start(profile)
    assert wait_until(lambda: True in events)
    FakePoll.pos = (500, 500); FakePoll.down = True
    time.sleep(0.05)
    FakePoll.down = False
    mon.stop(wait=True)
    assert events == [True]


# ------------------------------------------------------------------ config
def test_settings_persistence(tmp_path):
    p = tmp_path / 'ChaosLossAversion' / 'config.json'
    save_config({'hotkey': 'F6', 'volume': 40, 'send_esc': True, 'profile': {'box': [1, 2, 3, 4]}}, p)
    loaded = load_config(p)
    assert loaded == {'hotkey': 'F6', 'volume': 40, 'profile': {'box': [1, 2, 3, 4]}}
    p.write_text('{broken', encoding='utf-8')
    assert load_config(p) == {}
