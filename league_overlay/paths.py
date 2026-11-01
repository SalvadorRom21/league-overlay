"""Folders that belong to this app, not to League or to other projects."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
DRAGON_CACHE = CACHE / "ddragon"
WINDOW_STATE = CACHE / "window.json"
