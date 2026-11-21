"""Non-blocking item-slot calibration state machine (no Qt, no dialogs, no overlays).

Old flow problems this replaces:
* A full-screen, always-on-top selection window covered the whole desktop
  and grabbed every mouse click while the main window was hidden. If it
  failed to take keyboard focus (Windows foreground-lock while the game is
  in front), ESC never reached it and the desktop looked frozen.
* A failed border detection opened a modal QMessageBox and then immediately
  re-opened the full-screen overlay, which could loop.
* dxcam captures ran synchronously on the UI thread, sometimes while the
  monitor thread was still releasing its own camera.

New flow: hover the cursor and press the capture hotkey. Instructions update
in the main window. Every capture runs on a worker via ``executor``; results
from a cancelled/superseded session are discarded by generation number.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

MIN_SLOT_PX = 35
STEPS = ('ul', 'lr', 'confirm', 'neg', 'pos')


@dataclass
class View:
    step: str
    step_no: int
    total: int
    title: str
    text: str
    error: str = ''
    busy: bool = False
    confirm: bool = False
    preview: Any = None


@dataclass
class CalibrationDeps:
    cursor_pos: Callable[[], tuple]
    capture_frame: Callable[[tuple], Any]          # box -> RGB ndarray (worker thread)
    detect_border: Callable[[Any], tuple]          # RGB frame -> (x, y, w, h)
    build_signature: Callable[[Any, Any], dict]


class SyncExecutor:
    """Test/fallback executor. The Qt app supplies a threaded one."""

    def submit(self, fn, on_ok, on_err):
        try:
            result = fn()
        except Exception as exc:
            on_err(exc)
        else:
            on_ok(result)


def _box(p1, p2):
    left, right = sorted((int(p1[0]), int(p2[0])))
    top, bottom = sorted((int(p1[1]), int(p2[1])))
    return (left, top, right + 1, bottom + 1)


class CalibrationSession:
    def __init__(self, deps: CalibrationDeps, executor, capture_key: str,
                 on_update: Callable[[View], None],
                 on_finished: Callable[[dict], None],
                 on_cancelled: Callable[[], None]):
        self.deps = deps
        self.executor = executor
        self.capture_key = capture_key.upper()
        self.on_update = on_update
        self.on_finished = on_finished
        self.on_cancelled = on_cancelled
        self._active = False
        self.step: Optional[str] = None
        self.generation = 0
        self.busy = False
        self._first = None
        self._box = None
        self._neg = None
        self._preview = None

    # ------------------------------------------------------------ public API
    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        self.generation += 1
        self._active = True
        self.busy = False
        self._first = self._box = self._neg = self._preview = None
        self._go('ul')

    def cancel(self) -> None:
        if not self._active:
            return
        self._reset()
        self.on_cancelled()

    def capture(self) -> None:
        """Capture hotkey pressed."""
        if not self._active or self.busy:
            return
        step = self.step
        if step in ('ul', 'lr'):
            try:
                pos = tuple(self.deps.cursor_pos())
            except Exception as exc:
                self._go(step, error=f'Could not read cursor position: {exc}')
                return
            if step == 'ul':
                self._first = pos
                self._go('lr')
            else:
                self._corners_done(self._first, pos)
        elif step == 'neg':
            box = self._box
            self._run(lambda: self.deps.capture_frame(box), self._got_negative)
        elif step == 'pos':
            neg, box = self._neg, self._box

            def work():
                return self.deps.build_signature(neg, self.deps.capture_frame(box))
            self._run(work, self._got_signature)

    def answer(self, yes: bool) -> None:
        """Yes/No on the detected slot preview."""
        if not self._active or self.busy or self.step != 'confirm':
            return
        if yes:
            self._preview = None
            self._go('neg')
        else:
            self._first = None
            self._go('ul')

    # ------------------------------------------------------------ internals
    def _reset(self):
        self.generation += 1
        self._active = False
        self.step = None
        self.busy = False
        self._first = self._box = self._neg = self._preview = None

    def _text(self, step):
        k = self.capture_key
        return {
            'ul': ('Hover the cursor just OUTSIDE the UPPER-LEFT corner of the center Currency '
                   f'Tab slot border, then press {k}.'),
            'lr': ('Hover the cursor just OUTSIDE the LOWER-RIGHT corner of the same slot border, '
                   f'then press {k}.'),
            'confirm': 'Is this the center item slot of your Currency Tab?',
            'neg': ('Enter a keyword search in your stash. Place an item that DOES NOT match in the '
                    f'center slot. Move the cursor outside the slot, then press {k}.'),
            'pos': ('Now place an item that MATCHES the search in the center slot. Move the cursor '
                    f'outside the slot, then press {k}.'),
        }[step]

    def _go(self, step, error='', busy=False):
        self.step = step
        self.busy = busy
        self.on_update(View(step, STEPS.index(step) + 1, len(STEPS), 'Calibration in progress',
                            'Capturing…' if busy else self._text(step), error, busy,
                            step == 'confirm' and not busy,
                            self._preview if step == 'confirm' else None))

    def _run(self, work, on_ok):
        gen = self.generation
        step = self.step
        self._go(step, busy=True)

        def ok(result):
            if gen != self.generation or not self._active:
                return            # cancelled or restarted while working
            self.busy = False
            on_ok(result)

        def err(exc):
            if gen != self.generation or not self._active:
                return
            self.busy = False
            msg = str(exc) or exc.__class__.__name__
            if step in ('ul', 'lr'):
                self._first = None
                self._go('ul', error=msg)
            else:
                self._go(step, error=msg)

        self.executor.submit(work, ok, err)

    def _corners_done(self, p1, p2):
        box = _box(p1, p2)
        if box[2] - box[0] < MIN_SLOT_PX or box[3] - box[1] < MIN_SLOT_PX:
            self._first = None
            self._go('ul', error='Selection is too small. Include the entire slot border.')
            return

        def work():
            frame = self.deps.capture_frame(box)
            x, y, w, h = self.deps.detect_border(frame)
            refined = (box[0] + x, box[1] + y, box[0] + x + w, box[1] + y + h)
            return refined, frame[y:y + h, x:x + w].copy()

        self.step = 'lr'
        self._run(work, self._got_border)

    def _got_border(self, result):
        self._box, self._preview = result
        self._go('confirm')

    def _got_negative(self, frame):
        self._neg = frame
        self._go('pos')

    def _got_signature(self, sig):
        result = {'box': list(self._box), 'signature': sig}
        self._reset()
        self.on_finished(result)
