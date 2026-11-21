"""Persistent settings stored in %APPDATA%\\ChaosLossAversion\\config.json (atomic writes)."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG = Path(os.getenv('APPDATA', str(Path.home()))) / 'ChaosLossAversion' / 'config.json'

# Keys that older builds wrote and that must not survive a load.
_OBSOLETE = ('send_esc', 'overlay_enabled')

DEFAULTS = {
    'hotkey': 'F8',
    'capture_hotkey': 'F9',
    'overlay_hotkey': 'F7',
    'volume': 70,
    'overlay_width': 10,
    'overlay_opacity': 80,
}


def load_config(path: Path = None) -> dict:
    path = path or CONFIG
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            return {}
    except (OSError, ValueError):
        return {}
    for key in _OBSOLETE:
        config.pop(key, None)
    return config


def save_config(config: dict, path: Path = None) -> None:
    path = path or CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(config, indent=2), encoding='utf-8')
    tmp.replace(path)


def get(config: dict, key: str):
    return config.get(key, DEFAULTS.get(key))


def hotkey_names(config: dict) -> dict:
    keys = ('hotkey', 'capture_hotkey', 'overlay_hotkey')
    return {k: str(get(config, k)).upper() for k in keys}
