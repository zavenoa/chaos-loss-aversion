"""One-shot screen capture for calibration. Always called from a worker thread."""
from __future__ import annotations

import time


def capture_frame(box, before=None, attempts=30, interval=0.025):
    """Grab one RGB frame of ``box`` (physical pixels: left, top, right, bottom).

    ``before`` runs first (e.g. waiting for the monitor thread to release its
    DXGI duplication) so two cameras never fight over the same output.
    """
    if before is not None:
        before()
    import dxcam
    camera = dxcam.create(output_color='RGB')
    try:
        for _ in range(attempts):
            img = camera.grab(region=tuple(int(v) for v in box))
            if img is not None:
                return img.copy()
            time.sleep(interval)
        raise RuntimeError('Screen capture timed out. Make sure the game is visible and try again.')
    finally:
        try:
            camera.release()
        except Exception:
            pass
