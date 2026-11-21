"""Calibration signature building and per-frame match evaluation (numpy only)."""
from __future__ import annotations

import numpy as np

SIGNATURE_REGION = 'lower-border-v2'
DIFF_FLOOR = 35
MAX_POINTS = 24


def signature(neg, pos) -> dict:
    """Pick high-contrast, spatially spread pixels on the LOWER slot border.

    Hovering a Chaos Orb can cover the top half with its tooltip, so only the
    lower horizontal border and lower parts of the vertical borders are used.
    Same selection as z.1.0, but only candidate pixels are ranked instead of
    argsorting the whole image.
    """
    if neg.shape != pos.shape:
        raise ValueError('Calibration images have different dimensions')
    h, w = neg.shape[:2]
    diff = np.max(np.abs(neg.astype(np.int16) - pos.astype(np.int16)), axis=2)
    band = max(3, min(h, w) // 9)
    yy, xx = np.indices((h, w))
    mask = (yy >= int(h * 0.55)) & ((xx < band) | (xx >= w - band) | (yy >= h - band))
    mask[:2, :] = False
    mask[-2:, :] = False
    mask[:, :2] = False
    mask[:, -2:] = False
    mask &= diff >= DIFF_FLOOR
    cand = np.flatnonzero(mask.ravel())
    # Descending diff; ties broken by higher flat index, matching the old
    # argsort(...)[::-1] ordering exactly.
    order = np.lexsort((-cand, -diff.ravel()[cand]))
    ranked = cand[order]
    spacing2 = max(3, min(h, w) // 24) ** 2
    picks: list = []
    for idx in ranked:
        y, x = divmod(int(idx), w)
        if all((x - px) ** 2 + (y - py) ** 2 >= spacing2 for px, py in picks):
            picks.append((x, y))
            if len(picks) >= MAX_POINTS:
                break
    if len(picks) < 4:
        raise ValueError('Insufficient LOWER border contrast. Ensure the lower gold border is '
                         'visible in the positive calibration and recapture.')
    return {'points': picks,
            'negative': [neg[y, x].tolist() for x, y in picks],
            'positive': [pos[y, x].tolist() for x, y in picks],
            'threshold': 36, 'region': SIGNATURE_REGION}


def detect_slot_border(gray):
    """Find a supported, complete rectangular frame, not the largest random contour."""
    import cv2
    h, w = gray.shape
    if min(h, w) < 35:
        raise ValueError('Selection is too small. Include the entire slot border.')
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blur, 30, 105)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        if cw < 0.62 * w or ch < 0.62 * h or cw > 0.995 * w or ch > 0.995 * h:
            continue
        if x < 1 or y < 1 or x + cw >= w - 1 or y + ch >= h - 1:
            continue
        margin = max(2, min(cw, ch) // 30)
        roi = edges[y:y + ch, x:x + cw]
        top = np.mean(np.max(roi[:margin + 2, :], axis=0) > 0)
        bottom = np.mean(np.max(roi[-margin - 2:, :], axis=0) > 0)
        left = np.mean(np.max(roi[:, :margin + 2], axis=1) > 0)
        right = np.mean(np.max(roi[:, -margin - 2:], axis=1) > 0)
        coverage = min(top, bottom, left, right)
        if coverage < 0.52:
            continue
        area = (cw * ch) / (w * h)
        candidates.append((coverage * 0.35 + area * 0.65, x, y, cw, ch))
    if not candidates:
        raise ValueError('Could not verify all four outer slot borders. Capture corners slightly '
                         'OUTSIDE the slot frame so a little background is included.')
    _, x, y, cw, ch = max(candidates)
    return x, y, cw, ch


class MatchDetector:
    """Precomputed per-frame classifier for the monitor hot loop."""

    def __init__(self, sig: dict):
        if sig.get('region') != SIGNATURE_REGION:
            raise ValueError('This calibration predates lower-border sampling. Please recalibrate.')
        pts = np.asarray(sig['points'], dtype=np.intp)
        self.xs = pts[:, 0].copy()
        self.ys = pts[:, 1].copy()
        self.pos = np.asarray(sig['positive'], dtype=np.int16)
        self.neg = np.asarray(sig['negative'], dtype=np.int16)
        self.threshold = int(sig.get('threshold', 36))
        n = len(self.xs)
        self.need = max(4, (n * 3 + 3) // 4)

    def classify(self, frame):
        """Return (is_matching, is_negative) for one RGB frame."""
        pixels = frame[self.ys, self.xs].astype(np.int16)
        dp = np.abs(pixels - self.pos).max(axis=1)
        dn = np.abs(pixels - self.neg).max(axis=1)
        t = self.threshold
        pos_count = int(np.count_nonzero((dp <= t) & (dp + 18 < dn)))
        neg_count = int(np.count_nonzero((dn <= t) & (dn + 18 < dp)))
        need = self.need
        # Medians are only computed when the cheap vote counts already qualify.
        if pos_count >= need and pos_count > neg_count * 2:
            if float(np.median(dp)) + 12 < float(np.median(dn)):
                return True, False
        if neg_count >= need and neg_count > pos_count * 2:
            if float(np.median(dn)) + 12 < float(np.median(dp)):
                return False, True
        return False, False


def interior_sample(frame):
    """Sparse center sample used to confirm the item changed after a click."""
    h, w = frame.shape[:2]
    return frame[h // 3:2 * h // 3:4, w // 3:2 * w // 3:4].copy()


def interior_changed(current, baseline) -> bool:
    if baseline is None or baseline.shape != current.shape:
        return False
    delta = np.abs(current.astype(np.int16) - baseline.astype(np.int16)).max(axis=2)
    return float(np.mean(delta >= 32)) >= 0.20
