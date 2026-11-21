"""Read-only Windows queries. CLA never injects mouse or keyboard input.

Only two things are read: the physical cursor position (calibration corners
and the click-to-clear check) and whether the left button is down. Physical
pixels match DXGI capture coordinates regardless of Windows DPI scaling.
Importing on non-Windows is safe; calls raise OSError.
"""
from __future__ import annotations

import ctypes
import sys

IS_WINDOWS = sys.platform == 'win32'
VK_LBUTTON = 0x01


class POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


_user32 = None


def _u32():
    global _user32
    if not IS_WINDOWS:
        raise OSError('Windows only')
    if _user32 is None:
        from ctypes import wintypes as wt
        u = ctypes.WinDLL('user32', use_last_error=True)
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.GetPhysicalCursorPos.argtypes = [ctypes.POINTER(POINT)]
        u.GetPhysicalCursorPos.restype = wt.BOOL
        _user32 = u
    return _user32


def cursor_pos() -> tuple:
    p = POINT()
    if not _u32().GetPhysicalCursorPos(ctypes.byref(p)):
        raise OSError('GetPhysicalCursorPos failed')
    return (p.x, p.y)


def key_down(vk: int) -> bool:
    return bool(_u32().GetAsyncKeyState(vk) & 0x8000)
