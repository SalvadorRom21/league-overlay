"""Data Dragon cache for champion and item records.

The overlay downloads the latest patch once, then keeps working offline.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from league_overlay.model import Champion, Item, norm_name
from league_overlay.net import public_bytes
from league_overlay.paths import DRAGON_CACHE

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DATA_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/{name}.json"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
REFRESH_OK_SECONDS = 6 * 60 * 60
REFRESH_FAIL_SECONDS = 60


class DragonData:
    def __init__(
        self,
        version: str,
        champions: list[Champion],
        items: dict[int, Item],
        warning: str = "",
    ) -> None:
        self.version = version
        self.items = items
        self.warning = warning
        self.by_key: dict[int, Champion] = {}
        self.by_norm: dict[str, Champion] = {}
        for champ in champions:
            self.by_key[champ.key] = champ
            self.by_norm.setdefault(norm_name(champ.id), champ)
            self.by_norm.setdefault(norm_name(champ.name), champ)
        self.ready = bool(self.by_key and self.items)

    @classmethod
    def empty(cls, warning: str = "") -> DragonData:
        return cls("", [], {}, warning=warning)

    def champion_by_key(self, key: int) -> Champion | None:
        return self.by_key.get(key)

    def champion_from_client(self, raw: str, name: str) -> Champion | None:
        for token in (client_token(raw), name):
            if not token:
                continue
            found = self.by_norm.get(norm_name(token))
            if found is not None:
                return found
        return None


def client_token(raw: str) -> str:
    text = (raw or "").strip()
    if "displayname_" in text:
        text = text.split("displayname_", 1)[1]
    return text.split("/")[-1]


def _ints(values: Any) -> tuple[int, ...]:
    found: list[int] = []
    for value in values or []:
        try:
            found.append(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(found)


def parse_champions(payload: dict[str, Any]) -> list[Champion]:
    champions: list[Champion] = []
    for record in (payload.get("data") or {}).values():
        if not isinstance(record, dict):
            continue
        info = record.get("info") or {}
        try:
            key = int(record["key"])
        except (KeyError, TypeError, ValueError):
            continue
        champions.append(
            Champion(
                key=key,
                id=str(record.get("id") or ""),
                name=str(record.get("name") or record.get("id") or ""),
                tags=tuple(str(tag) for tag in record.get("tags") or []),
                attack=int(info.get("attack") or 0),
                magic=int(info.get("magic") or 0),
                defense=int(info.get("defense") or 0),
            )
        )
    return champions


def parse_items(payload: dict[str, Any]) -> dict[int, Item]:
    items: dict[int, Item] = {}
    for key, record in (payload.get("data") or {}).items():
        if not isinstance(record, dict):
            continue
        try:
            item_id = int(key)
        except (TypeError, ValueError):
            continue
        gold = record.get("gold") or {}
        maps = record.get("maps") or {}
        items[item_id] = Item(
            id=item_id,
            name=str(record.get("name") or f"Item {item_id}"),
            total=int(gold.get("total") or 0),
            base=int(gold.get("base") or 0),
            purchasable=bool(gold.get("purchasable", True)),
            summoners_rift=bool(maps.get("11")),
            in_store=record.get("inStore") is not False,
            tags=tuple(str(tag) for tag in record.get("tags") or []),
            from_ids=_ints(record.get("from")),
            required_champion=str(record.get("requiredChampion") or ""),
            howling_abyss=bool(maps.get("12")),
        )
    return items


def _read_json(path: Any) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Any, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


class Catalog:
    def __init__(self, cache_dir: Any = DRAGON_CACHE) -> None:
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._data = DragonData.empty(
            "Champion and item data is not cached yet. Connect once to download Data Dragon."
        )
        self._next_try = 0.0

    def snapshot(self) -> DragonData:
        with self._lock:
            return self._data

    def ensure(self) -> None:
        """Load the cache, then refresh from Data Dragon if it is missing or old."""
        self._load_cache()
        self._refresh()

    def _load_cache(self) -> None:
        version_path = self.cache_dir / "version.txt"
        champion_path = self.cache_dir / "champion.json"
        item_path = self.cache_dir / "item.json"
        if not (version_path.is_file() and champion_path.is_file() and item_path.is_file()):
            return
        try:
            version = version_path.read_text(encoding="utf-8").strip()
            data = DragonData(
                version,
                parse_champions(_read_json(champion_path)),
                parse_items(_read_json(item_path)),
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if data.ready:
            with self._lock:
                self._data = data

    def _refresh(self) -> None:
        now = time.time()
        if now < self._next_try and self.snapshot().ready:
            return
        try:
            versions = json.loads(public_bytes(VERSIONS_URL, timeout=12).decode("utf-8"))
            if not isinstance(versions, list) or not versions:
                raise ValueError("version list")
            version = str(versions[0])
            if not VERSION_RE.fullmatch(version):
                raise ValueError("version string")
            current = self.snapshot()
            if current.ready and current.version == version:
                self._next_try = now + REFRESH_OK_SECONDS
                return
            champion_raw = public_bytes(DATA_URL.format(version=version, name="champion"), timeout=30)
            item_raw = public_bytes(DATA_URL.format(version=version, name="item"), timeout=30)
            champions = parse_champions(json.loads(champion_raw.decode("utf-8")))
            items = parse_items(json.loads(item_raw.decode("utf-8")))
            data = DragonData(version, champions, items)
            if not data.ready:
                raise ValueError("empty dragon data")
            _atomic_write(self.cache_dir / "champion.json", champion_raw)
            _atomic_write(self.cache_dir / "item.json", item_raw)
            _atomic_write(self.cache_dir / "version.txt", version.encode("utf-8"))
            with self._lock:
                self._data = data
            self._next_try = time.time() + REFRESH_OK_SECONDS
        except Exception:
            self._next_try = time.time() + REFRESH_FAIL_SECONDS
            if not self.snapshot().ready:
                with self._lock:
                    self._data = DragonData.empty(
                        "Champion and item data is not cached yet. Connect once to download Data Dragon."
                    )
