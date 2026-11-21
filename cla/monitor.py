"""Capture-thread match monitor with click-to-clear latch."""
from __future__ import annotations

import threading
import time

from .detection import MatchDetector, interior_changed, interior_sample

TRANSITION_TIMEOUT_S = 0.25
IDLE_SLEEP_S = 0.002


def _default_camera():
    import dxcam
    return dxcam.create(output_color='RGB')


class _WinPoll:
    """Left-button edge + cursor position, read inline in the capture thread."""

    def __init__(self):
        from . import winapi
        self._key_down = winapi.key_down
        self._cursor = winapi.cursor_pos
        self._vk = winapi.VK_LBUTTON

    def left_down(self) -> bool:
        return self._key_down(self._vk)

    def cursor(self):
        return self._cursor()


class Monitor:
    def __init__(self, on_state, on_match, on_error, camera_factory=None, poll_factory=None):
        self.on_state = on_state
        self.on_match = on_match
        self.on_error = on_error
        self.camera_factory = camera_factory or _default_camera
        self.poll_factory = poll_factory or _WinPoll
        self.stop_event = threading.Event()
        self.thread = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        with self._lock:
            return self.thread is not None and self.thread.is_alive() and not self.stop_event.is_set()

    @property
    def alive(self) -> bool:
        with self._lock:
            return self.thread is not None and self.thread.is_alive()

    def start(self, profile) -> bool:
        with self._lock:
            if self.thread is not None and self.thread.is_alive():
                return False
            self.stop_event = threading.Event()
            stop = self.stop_event
            self.thread = threading.Thread(target=self._run, args=(profile, stop), daemon=True,
                                           name='CLA Monitor')
            self.thread.start()
        return True

    def stop(self, wait=False, timeout=2.5) -> bool:
        with self._lock:
            self.stop_event.set()
            thread = self.thread
        if wait and thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()

    def wait_stopped(self, timeout=2.5) -> bool:
        """Block (worker threads only) until any capture thread has released dxcam."""
        with self._lock:
            thread = self.thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()

    def _run(self, profile, stop):
        cam = None
        try:
            box = tuple(profile['box'])
            detector = MatchDetector(profile['signature'])
            poll = self.poll_factory()
            cam = self.camera_factory()
            self.on_state('MONITORING')
            classify = detector.classify
            grab = cam.grab
            left, top, right, bottom = box
            was_matching = False
            awaiting = False
            consecutive_negative = 0
            transition_changed = 0
            transition_started = 0.0
            previous_frame = None
            baseline = None
            button_was_down = poll.left_down()
            perf = time.perf_counter
            while not stop.is_set():
                button_down = poll.left_down()
                if button_down and not button_was_down and was_matching:
                    x, y = poll.cursor()
                    if left <= x < right and top <= y < bottom:
                        was_matching = False
                        awaiting = True
                        consecutive_negative = 0
                        transition_changed = 0
                        transition_started = perf()
                        # Interior is sampled lazily: only on a click, not every frame.
                        baseline = interior_sample(previous_frame) if previous_frame is not None else None
                        self.on_match(False)
                button_was_down = button_down
                frame = grab(region=box)
                if frame is None:
                    time.sleep(IDLE_SLEEP_S)
                    continue
                previous_frame = frame
                if awaiting:
                    _, is_negative = classify(frame)
                    consecutive_negative = consecutive_negative + 1 if is_negative else 0
                    changed = interior_changed(interior_sample(frame), baseline)
                    transition_changed = transition_changed + 1 if changed else 0
                    if (consecutive_negative >= 2 or transition_changed >= 2
                            or perf() - transition_started >= TRANSITION_TIMEOUT_S):
                        awaiting = False
                        baseline = None
                    # Re-evaluate on the next fresh capture, never the transition frame.
                    continue
                if not was_matching:
                    is_matching, _ = classify(frame)
                    if is_matching:
                        was_matching = True
                        self.on_match(True)
        except Exception as exc:
            if not stop.is_set():
                self.on_error(str(exc))
        finally:
            if cam is not None:
                try:
                    cam.release()
                except Exception:
                    pass
            self.on_state('NOT MONITORING')
