from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "character": {"name": "Pixel", "color": "#ff7a00", "start_x": 120, "ground_offset": 72},
    "authorized_apps": {
        "bloco de notas": ["notepad.exe"],
        "calculadora": ["calc.exe"],
        "paint": ["mspaint.exe"],
        "explorador": ["explorer.exe"],
    },
    "safety": {"allow_window_minimize": True, "allow_process_launch": True},
}


def load_config(path: Path) -> dict:
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    data = json.loads(path.read_text(encoding="utf-8"))
    result = DEFAULT_CONFIG.copy()
    result.update(data)
    return result
