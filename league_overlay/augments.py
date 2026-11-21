"""Mayhem augment names. Ids come from the local client. Names come from Community Dragon.

The live game API does not send the augments you picked. The client records
them on the match, as playerAugment ids. This module turns those ids into
names and a short description. There are no win rates here.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from league_overlay.net import public_bytes
from league_overlay.paths import CACHE

KIWI_URL = "https://raw.communitydragon.org/latest/game/maps/modespecificdata/kiwi.bin.json"
STRINGS_URL = "https://raw.communitydragon.org/latest/game/en_us/data/menu/en_us/lol.stringtable.json"
REFRESH_SECONDS = 12 * 60 * 60
_FLAG_PATTERNS = (
    ("grievous", re.compile(r"grievous|putrifier")),
    ("heal", re.compile(r"\b(heals?|healing|healed|lifesteal|omnivamp|spell\s*vamp)\b")),
    ("shield", re.compile(r"shields?")),
    ("armor", re.compile(r"\barmou?r\b")),
    ("mr", re.compile(r"magic resist")),
    ("attack_speed", re.compile(r"attack speed")),
)


def flags_from_text(*parts: str) -> tuple[str, ...]:
    text = " ".join(parts).casefold()
    return tuple(name for name, pattern in _FLAG_PATTERNS if pattern.search(text))


def pretty_augment_name(name_id: str) -> str:
    name = name_id[5:] if name_id.startswith("ARAM_") else name_id
    name = name.replace("_", " ")
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _plain(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"%[^%]+%", " ", text)
    text = re.sub(r"@[^@]+@", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Augment:
    id: int
    name: str
    blurb: str
    flags: tuple[str, ...]


class AugmentBook:
    def __init__(self, path: Path | None = None) -> None:
        self.path = CACHE / "augments.json" if path is None else path
        self._by_id: dict[int, Augment] = {}
        self.ready = False
        self._load()

    @classmethod
    def from_pairs(cls, rows: dict[int, tuple[str, str]]) -> AugmentBook:
        book = cls(path=Path(""))
        book._by_id = {
            aug_id: Augment(aug_id, name, blurb, flags_from_text(name, blurb))
            for aug_id, (name, blurb) in rows.items()
        }
        book.ready = True
        return book

    def get(self, aug_id: int) -> Augment | None:
        try:
            return self._by_id.get(int(aug_id))
        except (TypeError, ValueError):
            return None

    def ensure(self) -> None:
        """Load a compact name table, rebuilding it when the cache is old."""
        if self._fresh():
            self._load()
            return
        try:
            payload = _build_payload()
        except Exception:
            self._load()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self.path)
        self._load()

    def _fresh(self) -> bool:
        if not self.path.is_file():
            return False
        age = time.time() - self.path.stat().st_mtime
        return age < REFRESH_SECONDS

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        rows = payload.get("augments") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return
        found: dict[int, Augment] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                aug_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if aug_id <= 0:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            blurb = str(row.get("blurb") or "").strip()
            flags = tuple(str(flag) for flag in row.get("flags") or ())
            found[aug_id] = Augment(aug_id, name, blurb, flags)
        self._by_id = found
        self.ready = bool(found)


def resolve_augments(
    book: AugmentBook | None,
    ids: tuple[int, ...] | list[int],
    names: tuple[str, ...] | list[str] = (),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Display names, then the same lines with descriptions for scoring."""
    display: list[str] = []
    scoring: list[str] = []
    seen: set[str] = set()
    for raw_id in ids:
        try:
            aug_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if aug_id <= 0:
            continue
        aug = book.get(aug_id) if book is not None else None
        if aug is None:
            label = f"Augment {aug_id}"
            text = label
        else:
            label = aug.name
            text = f"{aug.name} {aug.blurb}".strip()
        if label in seen:
            continue
        display.append(label)
        scoring.append(text)
        seen.add(label)
    for name in names:
        cleaned = str(name).strip()
        if not cleaned or cleaned.isdigit() or cleaned in seen:
            continue
        display.append(cleaned)
        scoring.append(cleaned)
        seen.add(cleaned)
    return tuple(display), tuple(scoring)


def _string_map(payload: object) -> dict[str, str]:
    found: dict[str, str] = {}

    def add(key: object, value: object) -> None:
        if not isinstance(key, str) or not isinstance(value, str) or not key or not value:
            return
        found[key] = value
        found[key.casefold()] = value

    if isinstance(payload, dict):
        entries = payload.get("entries")
        if isinstance(entries, dict):
            for key, value in entries.items():
                if isinstance(value, str):
                    add(key, value)
                elif isinstance(value, dict):
                    add(key, value.get("value") or value.get("string") or "")
        elif isinstance(entries, list):
            for row in entries:
                if isinstance(row, dict):
                    add(row.get("key") or row.get("n") or "", row.get("value") or row.get("v") or "")
        else:
            for key, value in payload.items():
                if isinstance(value, str):
                    add(key, value)
    return found


def _lookup(strings: dict[str, str], key: str) -> str:
    if not key:
        return ""
    return _plain(strings.get(key) or strings.get(key.casefold()) or "")


def _cached_json(name: str, url: str) -> dict:
    path = CACHE / name
    fresh = path.is_file() and (time.time() - path.stat().st_mtime) < REFRESH_SECONDS
    if not fresh:
        raw = public_bytes(url, timeout=90)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _build_payload() -> dict:
    kiwi = _cached_json("kiwi.bin.json", KIWI_URL)
    try:
        strings = _string_map(_cached_json("lol.stringtable.json", STRINGS_URL))
    except Exception:
        strings = {}
    rows: list[dict] = []
    seen: set[int] = set()
    for key, value in kiwi.items():
        if not isinstance(value, dict) or not str(key).startswith("Maps/ModeSpecificData/Augments/"):
            continue
        if str(key).count("/") != 3:
            continue
        try:
            aug_id = int(value.get("AugmentPlatformId") or 0)
        except (TypeError, ValueError):
            continue
        name_id = str(value.get("AugmentNameId") or "")
        if aug_id <= 0 or not name_id or aug_id in seen:
            continue
        name = _lookup(strings, str(value.get("NameTra") or "")) or pretty_augment_name(name_id)
        blurb = _lookup(strings, str(value.get("DescriptionTra") or value.get("AugmentTooltipTra") or ""))
        if len(blurb) > 280:
            blurb = blurb[:277].rstrip() + "..."
        rows.append(
            {
                "id": aug_id,
                "name": name,
                "blurb": blurb,
                "flags": list(flags_from_text(name, blurb)),
            }
        )
        seen.add(aug_id)
    rows.sort(key=lambda row: int(row["id"]))
    return {"version": 1, "augments": rows}
