"""Build the text the overlay shows. Pure: no sockets and no Tk."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from league_overlay.augments import AugmentBook, names_from_screen, resolve_augments
from league_overlay.bridge import match_detail, recommend_bridge, suggest_bridge
from league_overlay.catalog import DragonData
from league_overlay.items import Recommendation, advise, boots_sell_line, enemy_build_line
from league_overlay.lcu import ChampSelect, LcuResult, MatchBoard
from league_overlay.live import TRINKETS, LiveResult, ParsedGame, parse_game
from league_overlay.modeinfo import ModeInfo, detect_mode
from league_overlay.model import Champion
from league_overlay.picks import normalize_position, suggest
from league_overlay.screen_augments import ScreenHit
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


def _slot_line(names: list[str], slots: int) -> str:
    body = "Items: " + ", ".join(names) if names else "Items: empty"
    return f"{body} · {slots} of 6 slots"


def _with_plan(detail: str, plan: tuple[str, ...], focus: str = "", boots_line: str = "") -> str:
    if not plan and not boots_line:
        return detail
    lines: list[str] = []
    if plan:
        line = "Plan: " + ", ".join(plan)
        if focus:
            line = f"Plan: {focus} — " + ", ".join(plan)
        lines.append(line)
    if boots_line:
        lines.append(boots_line)
    body = "\n".join(lines)
    return f"{detail}\n{body}" if detail else body


def _empty_buy(base: str, plan: tuple[str, ...], complete: bool, slots: int) -> str:
    if complete and len(plan) >= 6 and slots >= 6:
        return "All six slots are filled."
    if complete:
        return "No other finished item fits this match."
    return base


def _buy_view(rec: Recommendation, index: int) -> BuyView:
    afford = "Buy now" if rec.affordable else f"Need {rec.gold_short}g"
    item_line = f"{rec.buy_name} · {rec.cost}g · {afford}"
    if rec.buy_id == rec.completed_id:
        into_line = f"{rec.completed_total}g total"
    else:
        into_line = f"→ {rec.completed_name} · {rec.completed_total}g"
    if rec.have:
        into_line += " · have " + ", ".join(rec.have[:3])
    why = rec.why
    if rec.sell_name:
        sell = f"Sell {rec.sell_name} for {rec.completed_name}. {rec.sell_why}"
        why = f"{sell}\n{rec.why}" if rec.why else sell
    return BuyView("NEXT" if index == 0 else "ALSO", item_line, into_line, why, rec.affordable)


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


def _resolved_augments(
    book: AugmentBook | None,
    game: ParsedGame,
    board: MatchBoard | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    local_ids = list(game.augment_ids)
    enemy_ids = list(game.enemy_augment_ids)
    if board is not None and game.game_id and board.game_id == game.game_id:
        for aug_id in (board.local_player().augments if board.local_player() else ()):
            if aug_id not in local_ids:
                local_ids.append(aug_id)
        for player in board.enemy_players():
            for aug_id in player.augments:
                if aug_id not in enemy_ids:
                    enemy_ids.append(aug_id)
    yours, your_text = resolve_augments(book, local_ids, game.augments)
    enemies, enemy_text = resolve_augments(book, enemy_ids, game.enemy_augments)
    return yours, your_text, enemies, enemy_text


def _use_screen(
    book: AugmentBook | None,
    current: tuple[str, ...],
    current_text: tuple[str, ...],
    seen: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    extra, extra_text = names_from_screen(book, seen)
    names = list(current)
    text = list(current_text)
    for name, line in zip(extra, extra_text):
        if name not in names:
            names.append(name)
            text.append(line)
    return tuple(names), tuple(text)


def _ingame_panel(
    live: LiveResult,
    catalog: DragonData,
    mode: ModeInfo,
    lcu: LcuResult,
    augments: AugmentBook | None,
    screen: ScreenHit | None = None,
) -> InGamePanel:
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
    items_line = _slot_line(game.item_names, game.item_slots)
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
    yours, your_text, enemy_names, enemy_text = _resolved_augments(augments, game, lcu.board)
    cards: tuple[str, ...] = ()
    if screen is not None and mode.kind in {"mayhem", "aram-unconfirmed"}:
        yours, your_text = _use_screen(augments, yours, your_text, screen.yours)
        enemy_names, enemy_text = _use_screen(augments, enemy_names, enemy_text, screen.enemies)
        cards = tuple(names_from_screen(augments, screen.cards)[0])
    full = game.item_slots >= 6
    detail = ""
    plan: tuple[str, ...] = ()
    complete = False
    focus = ""
    boots_line = ""
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
            player_augments=yours,
            enemy_augments=enemy_names,
            player_augment_text=your_text,
            enemy_augment_text=enemy_text,
            enemy_builds=game.enemy_builds,
            augments_exposed=game.augments_exposed or bool(yours),
            mention_augments=mode.kind in {"mayhem", "aram-unconfirmed"},
            inventory_full=full,
            item_labels=game.item_labels,
            cards=cards,
        )
        advice = list(result.buys)
        threat = result.threat_line
        detail = result.detail
        plan = result.plan
        complete = result.complete
        focus = result.focus
        boots_line = boots_sell_line(result.boots_sell)
        empty = "No fountain buy stands out for this bridge."
    else:
        shop = advise(
            game.champion,
            game.enemies,
            game.owned,
            game.gold,
            catalog.items,
            enemy_builds=game.enemy_builds,
            inventory_full=full,
            item_labels=game.item_labels,
        )
        advice = list(shop.buys)
        plan = shop.plan
        complete = shop.complete
        focus = shop.focus
        boots_line = boots_sell_line(shop.boots_sell)
        detail = enemy_build_line(game.enemy_builds, catalog.items)
        empty = "No counter buy stands out for this team."
    detail = _with_plan(detail, plan, focus, boots_line)
    if not advice:
        return InGamePanel(
            True,
            _empty_buy(empty, plan, complete, game.item_slots),
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
    "rift": "Next buys from your champion, gold, the enemy champions, and the items they are buying.",
    "mayhem": "ARAM: Mayhem. You shop in the fountain, usually on death. Buys follow their champions, the items they are buying, and augments once the client records them.",
    "aram": "ARAM. You shop in the fountain, not a side lane. This is bridge advice, not Summoner's Rift. Buys follow their champions and the items they are buying.",
    "aram-unconfirmed": "Could not tell ARAM: Mayhem from normal ARAM. Showing ARAM advice, not Summoner's Rift.",
}
_POSTGAME_NOTE = "Augments the client saved for this match. The buy follows their champions and the items they finished with."
_SELECT_NOTES = {
    "rift": "A pick from the champions you can actually lock.",
    "mayhem": "ARAM: Mayhem. A bridge pick from the champions you can lock, including a bench swap or a reroll.",
    "aram": "ARAM. A bridge pick from the champions you can lock, including a bench swap or a reroll.",
    "aram-unconfirmed": "Could not tell ARAM: Mayhem from normal ARAM. Showing an ARAM pick, not a Summoner's Rift lane.",
}


def _saved_panel(
    lcu: LcuResult,
    catalog: DragonData,
    mode: ModeInfo,
    augments: AugmentBook | None,
) -> InGamePanel | None:
    board = lcu.board
    if board is None or not any(player.augments for player in board.players):
        return None
    local = board.local_player()
    yours, your_text = resolve_augments(augments, local.augments if local else (), ())
    enemy_ids: list[int] = []
    for player in board.enemy_players():
        enemy_ids.extend(player.augments)
    enemy_names, enemy_text = resolve_augments(augments, enemy_ids, ())
    you: Champion | None = None
    your_label = local.champion_name if local and local.champion_name else "Your champion"
    owned: dict[int, int] = {}
    item_ids = [item_id for item_id in (local.items if local else ()) if item_id not in TRINKETS]
    if local is not None:
        if local.champion_name:
            your_label = local.champion_name
        you = catalog.champion_by_key(local.champion_id)
        if you is not None:
            your_label = you.name
        for item_id in item_ids:
            owned[item_id] = owned.get(item_id, 0) + 1
    enemies: list[Champion] = []
    enemy_labels: list[str] = []
    builds: list[tuple[str, tuple[int, ...]]] = []
    for player in board.enemy_players():
        champ = catalog.champion_by_key(player.champion_id)
        label = player.champion_name or (champ.name if champ is not None else f"#{player.champion_id}")
        enemy_labels.append(label)
        if champ is not None:
            enemies.append(champ)
        enemy_items = tuple(item_id for item_id in player.items if item_id not in TRINKETS)
        if enemy_items:
            builds.append((label, enemy_items))
    enemy_line = "vs " + ", ".join(enemy_labels) if enemy_labels else "No enemies in this match."
    item_names = []
    for item_id in owned:
        meta = catalog.items.get(item_id)
        item_names.append(meta.name if meta is not None else str(item_id))
    slots = len(item_ids)
    items_line = _slot_line(item_names, slots)
    if you is None or not catalog.ready:
        detail = match_detail(yours, enemy_names, exposed=True, building=enemy_build_line(builds, catalog.items))
        return InGamePanel(True, "", your_label, enemy_line, "", items_line, detail)
    full = slots >= 6
    if mode.bridge:
        result = recommend_bridge(
            you,
            enemies,
            owned,
            0,
            catalog.items,
            mayhem_shop=mode.mayhem_shop,
            player_augments=yours,
            enemy_augments=enemy_names,
            player_augment_text=your_text,
            enemy_augment_text=enemy_text,
            enemy_builds=builds,
            augments_exposed=True,
            mention_augments=True,
            inventory_full=full,
        )
        advice = list(result.buys)
        detail = _with_plan(result.detail, result.plan, result.focus, boots_sell_line(result.boots_sell))
        message = "" if advice else _empty_buy("No fountain buy stands out for this bridge.", result.plan, result.complete, slots)
        return InGamePanel(
            True,
            message,
            your_label,
            enemy_line,
            result.threat_line,
            items_line,
            detail,
            tuple(_buy_view(rec, index) for index, rec in enumerate(advice)),
        )
    shop = advise(
        you,
        enemies,
        owned,
        0,
        catalog.items,
        enemy_builds=builds,
        inventory_full=full,
    )
    detail = _with_plan(
        match_detail(
            yours,
            enemy_names,
            exposed=True,
            building=enemy_build_line(builds, catalog.items),
        ),
        shop.plan,
        shop.focus,
        boots_sell_line(shop.boots_sell),
    )
    threat = threat_line(summarize(enemies)) if enemies else ""
    advice = list(shop.buys)
    return InGamePanel(
        True,
        "" if advice else _empty_buy("No counter buy stands out for this team.", shop.plan, shop.complete, slots),
        your_label,
        enemy_line,
        threat,
        items_line,
        detail,
        tuple(_buy_view(rec, index) for index, rec in enumerate(advice)),
    )


def build_view(
    live: LiveResult,
    lcu: LcuResult,
    catalog: DragonData,
    augments: AugmentBook | None = None,
    screen: ScreenHit | None = None,
) -> tuple[OverlayView, float]:
    detected = _detected(live, lcu)
    ingame = _ingame_panel(live, catalog, detected, lcu, augments, screen)
    picks = _pick_panel(lcu, catalog, detected)
    in_game = live.status == "ok" and ingame.active
    in_select = lcu.status == "champselect"
    saved = None if in_game or in_select else _saved_panel(lcu, catalog, detected, augments)
    if saved is not None:
        ingame = saved
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
    elif saved is not None:
        mode, headline, note, interval = (
            "postgame",
            f"Last game · {detected.label}",
            _POSTGAME_NOTE,
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
