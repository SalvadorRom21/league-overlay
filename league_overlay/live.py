"""League Live Client Data API on https://127.0.0.1:2999."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from league_overlay.catalog import DragonData
from league_overlay.model import Champion
from league_overlay.net import local_json

ALL_GAME_DATA = "https://127.0.0.1:2999/liveclientdata/allgamedata"
NAME_KEYS = ("summonerName", "riotId", "riotIdGameName", "gameName")
TRINKETS = {3330, 3340, 3363, 3364, 3513}


@dataclass
class LiveResult:
    status: str
    data: dict | None = None
    detail: str = ""

    @staticmethod
    def down() -> LiveResult:
        return LiveResult("down")


@dataclass
class ParsedGame:
    champion: Champion | None
    champion_label: str
    gold: float
    clock: str
    mode: str
    enemy_labels: list[str] = field(default_factory=list)
    enemies: list[Champion] = field(default_factory=list)
    owned: dict[int, int] = field(default_factory=dict)
    item_names: list[str] = field(default_factory=list)
    map_name: str = ""
    map_number: int = 0
    queue_id: int | None = None
    seconds: int = 0
    level: int = 0
    augments: tuple[str, ...] = ()
    enemy_augments: tuple[str, ...] = ()
    augments_exposed: bool = False


def fetch_live(timeout: float = 0.6) -> LiveResult:
    code, body, error = local_json(ALL_GAME_DATA, timeout=timeout)
    if error == "down" or code is None or code == 404:
        return LiveResult.down()
    if error == "badjson" or code != 200 or not isinstance(body, dict):
        return LiveResult("error", detail="Could not read the live game.")
    return LiveResult("ok", data=body)


def _identity(person: dict) -> set[str]:
    found: set[str] = set()
    for key in NAME_KEYS:
        value = person.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip().casefold()
        if not text:
            continue
        found.add(text)
        if "#" in text:
            found.add(text.split("#", 1)[0])
    return found


def match_player(active: dict, players: list) -> dict | None:
    wanted = _identity(active)
    if not wanted:
        return None
    for player in players:
        if isinstance(player, dict) and wanted & _identity(player):
            return player
    return None


def _clock(seconds: object) -> tuple[str, int]:
    try:
        total = max(0, int(float(seconds)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "0:00", 0
    return f"{total // 60}:{total % 60:02d}", total


def _number(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _augment_name(value: object) -> str:
    if isinstance(value, str):
        text = value.strip()
        if "displayname_" in text.casefold():
            text = text.split("displayname_", 1)[-1]
        return text.replace("_", " ").strip()
    if isinstance(value, dict):
        for key in ("name", "displayName", "rawDisplayName", "id"):
            found = _augment_name(value.get(key))
            if found:
                return found
    return ""


def _collect_augments(payload: object) -> tuple[list[str], bool]:
    """Read augment names from whatever list the live client attached."""
    found: list[str] = []
    exposed = False

    def walk(key: object, value: object) -> None:
        nonlocal exposed
        if not isinstance(key, str) or "augment" not in key.casefold():
            if isinstance(value, dict):
                for child_key, child in value.items():
                    walk(child_key, child)
            return
        exposed = True
        values = value if isinstance(value, list) else [value]
        for entry in values:
            name = _augment_name(entry)
            if name and name not in found:
                found.append(name)

    if isinstance(payload, dict):
        for key, value in payload.items():
            walk(key, value)
    return found, exposed


def _owned(player: dict, catalog: DragonData) -> tuple[dict[int, int], list[str]]:
    counts: dict[int, int] = {}
    names: list[str] = []
    for slot in player.get("items") or []:
        if not isinstance(slot, dict):
            continue
        if slot.get("consumable"):
            continue
        try:
            item_id = int(slot.get("itemID") or 0)
            count = int(slot.get("count") or 1)
        except (TypeError, ValueError):
            continue
        if item_id <= 0 or item_id in TRINKETS or count <= 0:
            continue
        counts[item_id] = counts.get(item_id, 0) + count
        label = str(slot.get("displayName") or "")
        if not label:
            meta = catalog.items.get(item_id)
            label = meta.name if meta is not None else ""
        if label:
            names.append(label if count == 1 else f"{label} x{count}")
    return counts, names


def parse_game(data: dict, catalog: DragonData) -> ParsedGame | None:
    if not isinstance(data, dict):
        return None
    active = data.get("activePlayer") if isinstance(data.get("activePlayer"), dict) else {}
    players = data.get("allPlayers") if isinstance(data.get("allPlayers"), list) else []
    if not players:
        return None
    try:
        gold = float(active.get("currentGold") or 0)
    except (TypeError, ValueError):
        gold = 0.0
    if math.isnan(gold) or gold < 0:
        gold = 0.0
    game_data = data.get("gameData") if isinstance(data.get("gameData"), dict) else {}
    clock, seconds = _clock(game_data.get("gameTime"))
    mode = str(game_data.get("gameMode") or "")
    map_name = str(game_data.get("mapName") or "")
    map_number = _number(game_data.get("mapNumber"))
    queue_id = _number(game_data.get("queueId") or game_data.get("queue")) or None
    me = match_player(active, players)
    if me is None:
        return ParsedGame(
            None,
            "Your champion",
            gold,
            clock,
            mode,
            map_name=map_name,
            map_number=map_number,
            queue_id=queue_id,
            seconds=seconds,
        )
    label = str(me.get("championName") or "Your champion")
    raw = str(me.get("rawChampionName") or "")
    champion = catalog.champion_from_client(raw, label)
    if champion is not None:
        label = champion.name
    team = me.get("team")
    enemies: list[Champion] = []
    enemy_labels: list[str] = []
    for player in players:
        if not isinstance(player, dict) or player is me:
            continue
        if team and player.get("team") == team:
            continue
        name = str(player.get("championName") or "Enemy")
        resolved = catalog.champion_from_client(str(player.get("rawChampionName") or ""), name)
        enemy_labels.append(resolved.name if resolved is not None else name)
        if resolved is not None:
            enemies.append(resolved)
    owned, item_names = _owned(me, catalog)
    player_augments, player_exposed = _collect_augments(me)
    active_augments, active_exposed = _collect_augments(active)
    augments: list[str] = []
    for name in (*player_augments, *active_augments):
        if name not in augments:
            augments.append(name)
    enemy_augments: list[str] = []
    for player in players:
        if not isinstance(player, dict) or player is me:
            continue
        if team and player.get("team") == team:
            continue
        names, _seen = _collect_augments(player)
        for name in names:
            if name not in enemy_augments:
                enemy_augments.append(name)
    level = _number(me.get("level") or active.get("level"))
    return ParsedGame(
        champion=champion,
        champion_label=label,
        gold=gold,
        clock=clock,
        mode=mode,
        enemy_labels=enemy_labels,
        enemies=enemies,
        owned=owned,
        item_names=item_names,
        map_name=map_name,
        map_number=map_number,
        queue_id=queue_id,
        seconds=seconds,
        level=level,
        augments=tuple(augments),
        enemy_augments=tuple(enemy_augments),
        augments_exposed=player_exposed or active_exposed,
    )
