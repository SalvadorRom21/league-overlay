"""Tell Summoner's Rift, ARAM, and ARAM: Mayhem apart.

Queue ids come from Community Dragon's queues.json (names "ARAM: Mayhem"
for 2400, 2401, 2403, 2405, 2410, 2450, 3240, 3270, and 3280, and "ARAM" for
450 and the other ids below). The live client calls the running Mayhem game
KIWI. That is the same mode: a game on this PC reported gameMode KIWI, and
Community Dragon's queue 2400 is named ARAM: Mayhem.
"""

from __future__ import annotations

from dataclasses import dataclass

# Featured Mayhem queues, including the tournament and "classic-ish" listings.
MAYHEM_QUEUES = frozenset({2400, 2401, 2403, 2405, 2410, 2450, 3240, 3270, 3280})
ARAM_QUEUES = frozenset({62, 63, 64, 65, 450, 860, 861, 930, 931})
MAYHEM_MODES = frozenset({"KIWI", "MAYHEM", "ARAMMAYHEM", "ARAM_MAYHEM"})
BRIDGE_MAP_WORDS = ("howling", "butcher", "koeshin")


@dataclass(frozen=True)
class ModeInfo:
    kind: str
    label: str

    @property
    def bridge(self) -> bool:
        return self.kind != "rift"

    @property
    def mayhem_shop(self) -> bool:
        """Mayhem-only legendaries are in the shop only when the mode is certain."""
        return self.kind == "mayhem"


def _queue(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def queue_id_from_gameflow(body: object) -> int | None:
    """Pull a queue id out of /lol-gameflow/v1/session. Missing data stays None."""
    if not isinstance(body, dict):
        return None
    game_data = body.get("gameData") if isinstance(body.get("gameData"), dict) else {}
    queue = game_data.get("queue") if isinstance(game_data.get("queue"), dict) else {}
    for candidate in (
        queue.get("id") if isinstance(queue, dict) else None,
        game_data.get("queueId"),
        body.get("queueId"),
    ):
        found = _queue(candidate)
        if found is not None:
            return found
    raw_queue = game_data.get("queue")
    return _queue(raw_queue)


def _map_is_bridge(map_name: str, map_number: object) -> bool:
    text = (map_name or "").casefold()
    if any(word in text for word in BRIDGE_MAP_WORDS):
        return True
    compact = text.replace(" ", "")
    if compact in {"map12", "12"}:
        return True
    number = _queue(map_number)
    return number == 12


def detect_mode(
    *,
    game_mode: str = "",
    map_name: str = "",
    map_number: object = None,
    queue_id: int | None = None,
    bridge_select: bool = False,
) -> ModeInfo:
    """Classify the current lobby or game.

    Mayhem wins if either the queue or the live gameMode says so. A normal
    ARAM queue or gameMode ARAM is normal ARAM. A Howling Abyss-style map, or
    a champion select that has rerolls but no queue, is ARAM advice with an
    explicit note that Mayhem could not be separated from ARAM.
    """
    mode = (game_mode or "").strip().upper().replace(" ", "").replace(":", "")
    queue = _queue(queue_id)
    if queue in MAYHEM_QUEUES or mode in MAYHEM_MODES:
        return ModeInfo("mayhem", "ARAM: Mayhem")
    if queue in ARAM_QUEUES or mode == "ARAM":
        return ModeInfo("aram", "ARAM")
    if _map_is_bridge(map_name, map_number) or bridge_select:
        return ModeInfo("aram-unconfirmed", "ARAM")
    return ModeInfo("rift", "Summoner's Rift")
