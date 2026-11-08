"""Build the text the overlay shows. Pure: no sockets and no Tk."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from league_overlay.bridge import recommend_bridge, suggest_bridge
from league_overlay.catalog import DragonData
from league_overlay.items import Recommendation, recommend
from league_overlay.lcu import ChampSelect, LcuResult
from league_overlay.live import LiveResult, ParsedGame, parse_game
from league_overlay.modeinfo import ModeInfo, detect_mode
from league_overlay.model import Champion
from league_overlay.picks import normalize_position, suggest
from league_overlay.threats import threat_line, summarize

ACTIVE_INTERVAL = 0.35
IDLE_INTERVAL = 2.0


@dataclass(frozen=True)
class BuyView:
    title: str
    item_line: str
    into_line: str
    why: str
    affordable: bool


@dataclass(frozen=True)
class InGamePanel:
    active: bool
    message: str = ""
    champion_line: str = ""
    enemy_line: str = ""
    threat_line: str = ""
    items_line: str = ""
    detail_line: str = ""
    buys: tuple[BuyView, ...] = ()


@dataclass(frozen=True)
class PickPanel:
    active: bool
    message: str = ""
    pick_line: str = ""
    why: str = ""
    alt_line: str = ""
    team_line: str = ""
    meta_line: str = ""


@dataclass(frozen=True)
class OverlayView:
    mode: str
    headline: str
    note: str
    warning: str = ""
    ingame: InGamePanel = field(default_factory=lambda: InGamePanel(False, "No active game."))
    picks: PickPanel = field(default_factory=lambda: PickPanel(False, "Champion select is unavailable."))


def _buy_view(rec: Recommendation, index: int) -> BuyView:
    afford = "Buy now" if rec.affordable else f"Need {rec.gold_short}g"
    item_line = f"{rec.buy_name} · {rec.cost}g · {afford}"
    if rec.buy_id == rec.completed_id:
        into_line = f"{rec.completed_total}g total"
    else:
        into_line = f"→ {rec.completed_name} · {rec.completed_total}g"
    if rec.have:
        into_line += " · have " + ", ".join(rec.have[:3])
    return BuyView("NEXT" if index == 0 else "ALSO", item_line, into_line, rec.why, rec.affordable)


def _champion_line(game: ParsedGame) -> str:
    gold = math.floor(game.gold)
    return f"{game.champion_label} · {gold}g · {game.clock}"


def _detected(live: LiveResult, lcu: LcuResult) -> ModeInfo:
    game_mode = ""
    map_name = ""
    map_number = None
    queue = lcu.queue_id
    if live.status == "ok" and isinstance(live.data, dict):
        game_data = live.data.get("gameData") if isinstance(live.data.get("gameData"), dict) else {}
        game_mode = str(game_data.get("gameMode") or "")
        map_name = str(game_data.get("mapName") or "")
        map_number = game_data.get("mapNumber")
        if queue is None:
            raw_queue = game_data.get("queueId")
            if raw_queue is None and not isinstance(game_data.get("queue"), dict):
                raw_queue = game_data.get("queue")
            try:
                parsed = int(raw_queue)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                parsed = 0
            if parsed > 0:
                queue = parsed
    bridge_select = False
    select = lcu.select
    if lcu.status == "champselect" and select is not None:
        bridge_select = select.rerolls_remaining is not None and not normalize_position(select.position)
    return detect_mode(
        game_mode=game_mode,
        map_name=map_name,
        map_number=map_number,
        queue_id=queue,
        bridge_select=bridge_select,
    )


def _ingame_panel(live: LiveResult, catalog: DragonData, mode: ModeInfo) -> InGamePanel:
    if live.status == "down":
        return InGamePanel(False, "No active game.")
    if live.status != "ok" or not isinstance(live.data, dict):
        return InGamePanel(False, "Could not read the live game. Retrying.")
    game = parse_game(live.data, catalog)
    if game is None:
        return InGamePanel(False, "No active game.")
    champion_line = _champion_line(game)
    enemy_line = "vs " + ", ".join(game.enemy_labels) if game.enemy_labels else "No enemies in this game."
    threat = threat_line(summarize(game.enemies)) if game.enemies else "No enemy champions read yet."
    items_line = "Items: " + ", ".join(game.item_names) if game.item_names else "Items: empty"
    if not catalog.ready:
        return InGamePanel(
            True,
            "In a game. Item names are waiting on the Data Dragon cache.",
            champion_line,
            enemy_line,
            threat,
            items_line,
        )
    if game.champion is None:
        return InGamePanel(
            True,
            "In a game, but your champion was not matched yet.",
            champion_line,
            enemy_line,
            threat,
            items_line,
        )
    detail = ""
    if mode.bridge:
        early = (game.level > 0 and game.level <= 4) or (game.level <= 0 and 0 < game.seconds < 240)
        result = recommend_bridge(
            game.champion,
            game.enemies,
            game.owned,
            game.gold,
            catalog.items,
            mayhem_shop=mode.mayhem_shop,
            early=early,
            player_augments=game.augments,
            enemy_augments=game.enemy_augments,
            augments_exposed=game.augments_exposed,
            mention_augments=mode.kind in {"mayhem", "aram-unconfirmed"},
        )
        advice = list(result.buys)
        threat = result.threat_line
        detail = result.detail
        empty = "No fountain buy stands out for this bridge."
    else:
        advice = recommend(game.champion, game.enemies, game.owned, game.gold, catalog.items)
        empty = "No counter buy stands out for this team."
    if not advice:
        return InGamePanel(
            True,
            empty,
            champion_line,
            enemy_line,
            threat,
            items_line,
            detail,
        )
    return InGamePanel(
        True,
        "",
        champion_line,
        enemy_line,
        threat,
        items_line,
        detail,
        tuple(_buy_view(rec, index) for index, rec in enumerate(advice)),
    )


def _names(ids: list[int], catalog: DragonData) -> str:
    labels: list[str] = []
    for champion_id in ids:
        champ = catalog.champion_by_key(champion_id)
        labels.append(champ.name if champ is not None else f"#{champion_id}")
    return ", ".join(labels)


def _resolve(ids: list[int], catalog: DragonData) -> list[Champion]:
    found: list[Champion] = []
    for champion_id in ids:
        champ = catalog.champion_by_key(champion_id)
        if champ is not None:
            found.append(champ)
    return found


def _pick_panel(lcu: LcuResult, catalog: DragonData, mode: ModeInfo) -> PickPanel:
    if lcu.status in {"down", "error"}:
        return PickPanel(False, "Champion select is unavailable.")
    if lcu.status != "champselect" or lcu.select is None:
        return PickPanel(False, "Not in champion select.")
    select: ChampSelect = lcu.select
    allies = _names(select.allies, catalog)
    enemies = _names(select.enemies, catalog)
    team = f"Allies: {allies or 'none shown'}    Enemies: {enemies or 'none shown'}"
    if not catalog.by_key:
        return PickPanel(True, "Champion select is open, but champion data is not cached yet.", team_line=team)
    if select.pickable is None:
        return PickPanel(
            True,
            "In champion select, but the champions you can lock could not be read.",
            team_line=team,
        )
    position = normalize_position(select.position)
    yours = select.locked_id or select.local_champion_id
    allies = _resolve(select.allies, catalog)
    enemies = _resolve(select.enemies, catalog)
    taken = set(select.allies) | set(select.enemies) | set(select.bans)
    if mode.bridge:
        bridge_pick = suggest_bridge(
            select.pickable,
            allies,
            enemies,
            set(select.bans),
            catalog,
            locked_id=yours,
            taken_ids=taken,
            rerolls=select.rerolls_remaining,
        )
        if bridge_pick is None:
            return PickPanel(True, "No champions left that you can lock.", team_line=team)
        current = catalog.champion_by_key(yours) if yours else None
        current_name = current.name if current is not None else (f"#{yours}" if yours else "")
        if bridge_pick.action == "reroll":
            left = bridge_pick.rerolls or 0
            pick_line = f"Reroll ({left} left)"
            if current_name:
                pick_line += f"    your champion: {current_name}"
        elif bridge_pick.action == "bench":
            pick_line = f"Take {bridge_pick.champion.name} from the bench"
            if current_name:
                pick_line += f"    (your champion: {current_name})"
        elif bridge_pick.action == "keep":
            pick_line = f"Keep {bridge_pick.champion.name}"
        else:
            pick_line = f"Pick {bridge_pick.champion.name}"
        alt = "Also " + ", ".join(bridge_pick.alternatives) if bridge_pick.alternatives else ""
        meta = f"From {bridge_pick.considered} you can lock"
        if bridge_pick.rerolls is None:
            meta += " · reroll count was not in the client session"
        else:
            meta += f" · rerolls left: {bridge_pick.rerolls}"
        return PickPanel(True, "", pick_line, bridge_pick.why, alt, team, meta)
    suggestion = suggest(
        select.pickable,
        allies,
        enemies,
        set(select.bans),
        position,
        catalog,
        locked_id=yours,
        taken_ids=taken,
    )
    if suggestion is None:
        return PickPanel(True, "No champions left that you can lock.", team_line=team)
    pick_line = f"Pick {suggestion.champion.name}"
    if yours:
        current = catalog.champion_by_key(yours)
        current_name = current.name if current is not None else f"#{yours}"
        if yours == suggestion.champion.key:
            pick_line = f"Your pick matches: {suggestion.champion.name}"
        else:
            pick_line = f"Pick {suggestion.champion.name}    (your pick: {current_name})"
    alt = "Also " + ", ".join(suggestion.alternatives) if suggestion.alternatives else ""
    meta = f"From {suggestion.considered} you can lock"
    if not position:
        meta += " · no role set, this is a counter pick"
    return PickPanel(True, "", pick_line, suggestion.why, alt, team, meta)


_NOTES = {
    "rift": "Next buys from your champion, gold, and the five enemies.",
    "mayhem": "ARAM: Mayhem. You shop in the fountain, usually on death. Healing and poke matter more than a Summoner's Rift lane.",
    "aram": "ARAM. You shop in the fountain, not a side lane. This is bridge advice, not Summoner's Rift.",
    "aram-unconfirmed": "Could not tell ARAM: Mayhem from normal ARAM. Showing ARAM advice, not Summoner's Rift.",
}
_SELECT_NOTES = {
    "rift": "A pick from the champions you can actually lock.",
    "mayhem": "ARAM: Mayhem. A bridge pick from the champions you can lock, including a bench swap or a reroll.",
    "aram": "ARAM. A bridge pick from the champions you can lock, including a bench swap or a reroll.",
    "aram-unconfirmed": "Could not tell ARAM: Mayhem from normal ARAM. Showing an ARAM pick, not a Summoner's Rift lane.",
}


def build_view(live: LiveResult, lcu: LcuResult, catalog: DragonData) -> tuple[OverlayView, float]:
    detected = _detected(live, lcu)
    ingame = _ingame_panel(live, catalog, detected)
    picks = _pick_panel(lcu, catalog, detected)
    in_game = live.status == "ok" and ingame.active
    in_select = lcu.status == "champselect"
    if in_game:
        mode, headline, note, interval = (
            "ingame",
            f"In game · {detected.label}",
            _NOTES[detected.kind],
            ACTIVE_INTERVAL,
        )
    elif in_select:
        mode, headline, note, interval = (
            "champselect",
            f"Champion select · {detected.label}",
            _SELECT_NOTES[detected.kind],
            ACTIVE_INTERVAL,
        )
    elif lcu.status == "open":
        mode, headline, note, interval = (
            "idle",
            "League is open",
            "Waiting for champion select or a game.",
            IDLE_INTERVAL,
        )
    else:
        mode, headline, note, interval = (
            "waiting",
            "Waiting for League",
            "Start League on this PC. This window stays here until a game or champion select begins.",
            IDLE_INTERVAL,
        )
    warning = "" if catalog.ready else (
        catalog.warning or "Champion and item data is not cached yet. Connect once to download Data Dragon."
    )
    return OverlayView(mode, headline, note, warning, ingame, picks), interval
