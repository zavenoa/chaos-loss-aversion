"""Edge-triggered, modifier-agnostic global hotkeys on top of ``keyboard``.

Why not keyboard.add_hotkey:
* It matches the exact modifier set, so F8 pressed while Shift/Ctrl is
  held (common while crafting) arrives as "shift+f8" and does nothing.
* Keyboard auto-repeat re-fires it, so holding a key toggles start/stop
  repeatedly.
Here each physical press fires exactly once, whatever modifiers are down.
Callbacks run on the keyboard hook thread: keep them to a Qt signal emit.
"""
from __future__ import annotations

import threading
import time

# Windows' longest keyboard repeat delay is 1 s. A press arriving after a longer
# gap is a new physical press even if its key-up was never seen (UAC, alt-tab).
REPEAT_GAP_S = 1.1


class _KeyboardLib:
    def on_press_key(self, key, cb):
        import keyboard
        return keyboard.on_press_key(key, cb, suppress=False)

    def on_release_key(self, key, cb):
        import keyboard
        return keyboard.on_release_key(key, cb, suppress=False)

    def unhook(self, handle):
        import keyboard
        keyboard.unhook(handle)


def normalize(key: str) -> str:
    return str(key).strip().lower()


class HotkeyManager:
    def __init__(self, lib=None, clock=time.monotonic):
        self.lib = lib or _KeyboardLib()
        self.clock = clock
        self._last = {}       # key -> time of last down event
        self._lock = threading.Lock()
        self._bindings = {}   # name -> (key, callback)
        self._handles = {}    # name -> [hook handles]
        self._down = set()    # keys physically down (for auto-repeat suppression)

    def _make_press(self, name, key):
        def on_press(_event=None):
            now = self.clock()
            with self._lock:
                last = self._last.get(key, -1e9)
                self._last[key] = now
                if key in self._down and now - last < REPEAT_GAP_S:
                    return            # auto-repeat
                self._down.add(key)
                binding = self._bindings.get(name)
            if binding is not None:
                binding[1]()
        return on_press

    def _make_release(self, key):
        def on_release(_event=None):
            with self._lock:
                self._down.discard(key)
        return on_release

    def bind(self, name: str, key: str, callback) -> None:
        key = normalize(key)
        self.unbind(name)
        handles = [self.lib.on_press_key(key, self._make_press(name, key)),
                   self.lib.on_release_key(key, self._make_release(key))]
        with self._lock:
            self._bindings[name] = (key, callback)
            self._handles[name] = handles

    def unbind(self, name: str) -> None:
        with self._lock:
            handles = self._handles.pop(name, [])
            binding = self._bindings.pop(name, None)
            if binding is not None:
                self._down.discard(binding[0])
        for h in handles:
            try:
                self.lib.unhook(h)
            except Exception:
                pass

    def clear(self) -> None:
        with self._lock:
            names = list(self._bindings)
        for name in names:
            self.unbind(name)

    def bound(self, name: str) -> bool:
        with self._lock:
            return name in self._bindings
