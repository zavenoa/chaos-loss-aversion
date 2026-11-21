"""Calibration state machine: start/complete/cancel/restart, never blocking."""
import threading
import time

import numpy as np
import pytest

from cla.calibration import CalibrationDeps, CalibrationSession, SyncExecutor


class DeferredExecutor:
    """Holds work until run_all(), emulating a slow worker thread."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, ok, err):
        self.jobs.append((fn, ok, err))

    def run_all(self):
        jobs, self.jobs = self.jobs, []
        for fn, ok, err in jobs:
            try:
                r = fn()
            except Exception as e:
                err(e)
            else:
                ok(r)


class Harness:
    def __init__(self, executor=None, cursor=None, border=(2, 2, 40, 40)):
        self.cursor = list(cursor or [(10, 10), (60, 60)])
        self.views, self.finished, self.cancelled = [], [], []
        frame = np.zeros((51, 51, 3), np.uint8)
        self.captures = 0

        def capture(box):
            self.captures += 1
            return frame

        self.deps = CalibrationDeps(
            cursor_pos=lambda: self.cursor.pop(0) if self.cursor else (0, 0),
            capture_frame=capture,
            detect_border=lambda f: border,
            build_signature=lambda n, p: {'sig': True})
        self.session = CalibrationSession(self.deps, executor or SyncExecutor(), 'F9',
                                          self.views.append, self.finished.append,
                                          lambda: self.cancelled.append(1))


def complete(s):
    s.start(); s.capture(); s.capture(); s.answer(True); s.capture(); s.capture()


def test_flow_completes():
    h = Harness()
    s = h.session
    s.start()
    assert s.step == 'ul' and 'F9' in h.views[-1].text and 'UPPER-LEFT' in h.views[-1].text
    s.capture(); assert s.step == 'lr'
    s.capture(); assert s.step == 'confirm' and h.views[-1].confirm
    assert h.views[-1].preview.shape == (40, 40, 3)
    s.answer(True); assert s.step == 'neg'
    s.capture(); assert s.step == 'pos'
    s.capture()
    assert not s.active
    assert h.finished[-1] == {'box': [12, 12, 52, 52], 'signature': {'sig': True}}


def test_corner_order_does_not_matter():
    h = Harness(cursor=[(60, 60), (10, 10)])
    complete(h.session)
    assert h.finished[-1]['box'] == [12, 12, 52, 52]


def test_reject_goes_back_to_corners():
    h = Harness(cursor=[(10, 10), (60, 60), (10, 10), (60, 60)])
    s = h.session
    s.start(); s.capture(); s.capture(); s.answer(False)
    assert s.step == 'ul'
    s.capture(); s.capture()
    assert s.step == 'confirm'


def test_too_small_shows_inline_error():
    h = Harness(cursor=[(10, 10), (20, 20)])
    s = h.session
    s.start(); s.capture(); s.capture()
    assert s.step == 'ul' and 'too small' in h.views[-1].error and s.active


def test_detection_failure_is_inline_not_a_loop():
    h = Harness()
    h.deps.detect_border = lambda f: (_ for _ in ()).throw(ValueError('no border'))
    s = h.session
    s.start(); s.capture(); s.capture()
    assert s.step == 'ul' and h.views[-1].error == 'no border' and s.active
    assert h.captures == 1


def test_capture_failure_keeps_step():
    h = Harness()
    s = h.session
    s.start(); s.capture(); s.capture(); s.answer(True)
    h.deps.capture_frame = lambda box: (_ for _ in ()).throw(RuntimeError('timed out'))
    s.capture()
    assert s.step == 'neg' and h.views[-1].error == 'timed out' and not s.busy


@pytest.mark.parametrize('at_step', range(5))
def test_cancel_at_every_step_restores_idle(at_step):
    h = Harness()
    s = h.session
    s.start()
    actions = [s.capture, s.capture, lambda: s.answer(True), s.capture]
    for a in actions[:at_step]:
        a()
    s.cancel()
    assert not s.active and s.step is None and h.cancelled == [1]
    s.capture(); s.answer(True)               # stray hotkeys after cancel are ignored
    assert not h.finished and not s.active


def test_stale_worker_result_after_cancel_is_ignored():
    ex = DeferredExecutor()
    h = Harness(executor=ex)
    s = h.session
    s.start(); s.capture(); s.capture()
    assert s.busy
    s.capture()                                # busy: ignored, no double capture
    assert len(ex.jobs) == 1
    s.cancel()
    ex.run_all()
    assert not s.active and not h.finished


def test_stale_result_after_restart_is_ignored():
    ex = DeferredExecutor()
    h = Harness(executor=ex, cursor=[(10, 10), (60, 60), (10, 10)])
    s = h.session
    s.start(); s.capture(); s.capture()
    s.start(); s.capture()
    ex.run_all()
    assert s.step == 'lr' and not s.busy


def test_repeated_start_complete_cancel_cycles():
    for i in range(300):
        h = Harness(cursor=[(10, 10), (60, 60)] * 3)
        s = h.session
        s.start(); s.capture()
        if i % 3 == 0:
            s.cancel()
            assert not s.active
            s.start(); s.capture()
        s.capture(); s.answer(True); s.capture(); s.capture()
        assert not s.active and h.finished


def test_threaded_executor_never_blocks_caller():
    gate, done = threading.Event(), threading.Event()

    class ThreadExec:
        def submit(self, fn, ok, err):
            def run():
                gate.wait(5)
                try:
                    ok(fn())
                except Exception as e:
                    err(e)
                done.set()
            threading.Thread(target=run, daemon=True).start()

    h = Harness(executor=ThreadExec())
    s = h.session
    s.start(); s.capture()
    t0 = time.monotonic(); s.capture(); elapsed = time.monotonic() - t0
    assert elapsed < 0.05 and s.busy
    s.cancel()
    gate.set(); done.wait(2)
    assert not s.active and not h.finished
