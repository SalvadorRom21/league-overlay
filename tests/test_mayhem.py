"""ARAM: Mayhem detection, fountain buys, and rerolls. No network."""

from __future__ import annotations

import unittest

from league_overlay.catalog import DragonData
from league_overlay.items import recommend
from league_overlay.lcu import ChampSelect, LcuResult, parse_session
from league_overlay.live import LiveResult
from league_overlay.modeinfo import detect_mode, queue_id_from_gameflow
from league_overlay.model import Champion, Item
from league_overlay.view import build_view


def champ(key: int, champ_id: str, name: str, tags: list[str], attack: int, magic: int, defense: int) -> Champion:
    return Champion(key, champ_id, name, tuple(tags), attack, magic, defense)


def shop_item(
    item_id: int,
    name: str,
    total: int,
    *,
    rift: bool = True,
    abyss: bool = True,
    tags: tuple[str, ...] = (),
) -> Item:
    return Item(
        id=item_id,
        name=name,
        total=total,
        base=total,
        purchasable=True,
        summoners_rift=rift,
        in_store=True,
        tags=tags,
        from_ids=(),
        required_champion="",
        howling_abyss=abyss,
    )


AHRI = champ(103, "Ahri", "Ahri", ["Mage", "Assassin"], 3, 8, 4)
ZED = champ(238, "Zed", "Zed", ["Assassin"], 9, 1, 2)
TALON = champ(91, "Talon", "Talon", ["Assassin"], 9, 1, 3)
QIYANA = champ(246, "Qiyana", "Qiyana", ["Assassin"], 0, 4, 2)
NAAFIRI = champ(950, "Naafiri", "Naafiri", ["Assassin", "Fighter"], 9, 0, 5)
RENGAR = champ(107, "Rengar", "Rengar", ["Assassin", "Fighter"], 7, 2, 4)
SORAKA = champ(16, "Soraka", "Soraka", ["Support", "Mage"], 2, 7, 5)
MALPHITE = champ(54, "Malphite", "Malphite", ["Tank", "Mage"], 5, 7, 9)
JINX = champ(222, "Jinx", "Jinx", ["Marksman"], 9, 4, 2)
DARIUS = champ(122, "Darius", "Darius", ["Fighter", "Tank"], 9, 1, 5)
XERATH = champ(101, "Xerath", "Xerath", ["Mage"], 1, 10, 3)
ZIGGS = champ(115, "Ziggs", "Ziggs", ["Mage"], 2, 9, 4)
BRAND = champ(63, "Brand", "Brand", ["Mage"], 2, 9, 2)

ASSASSINS = [ZED, TALON, QIYANA, NAAFIRI, RENGAR]


def bridge_catalog(*extra: Item) -> DragonData:
    items = {
        entry.id: entry
        for entry in (
            shop_item(3157, "Zhonya's Hourglass", 3250),
            shop_item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
            shop_item(3102, "Banshee's Veil", 3000),
            shop_item(123430, "Rite of Ruin", 3000, rift=False),
            shop_item(3742, "Dead Man's Plate", 2900),
            shop_item(3165, "Morellonomicon", 2850),
            shop_item(3075, "Thornmail", 2450),
            shop_item(3083, "Warmog's Armor", 3100),
            *extra,
        )
    }
    return DragonData("test", [AHRI, *ASSASSINS, SORAKA, MALPHITE, JINX, DARIUS, XERATH, ZIGGS, BRAND], items)


def buy_text(view) -> str:
    return " ".join(f"{buy.item_line} {buy.into_line} {buy.why}" for buy in view.ingame.buys)


def game(mode: str, *, gold: int = 2000, map_name: str = "", queue: int | None = None, augments: list | None = None) -> dict:
    me: dict = {
        "summonerName": "Sal",
        "championName": "Ahri",
        "team": "ORDER",
        "items": [],
        "level": 11,
    }
    if augments is not None:
        me["augments"] = augments
    payload = {
        "activePlayer": {"summonerName": "Sal", "currentGold": gold, "level": 11},
        "allPlayers": [
            me,
            {"summonerName": "a", "championName": "Zed", "team": "CHAOS", "items": []},
            {"summonerName": "b", "championName": "Talon", "team": "CHAOS", "items": []},
            {"summonerName": "c", "championName": "Qiyana", "team": "CHAOS", "items": []},
            {"summonerName": "d", "championName": "Naafiri", "team": "CHAOS", "items": []},
            {"summonerName": "e", "championName": "Rengar", "team": "CHAOS", "items": []},
        ],
        "gameData": {"gameTime": 754, "gameMode": mode, "mapName": map_name},
    }
    if queue is not None:
        payload["gameData"]["queueId"] = queue
    return payload


class ModeTests(unittest.TestCase):
    def test_kiwi_and_queue_2400_are_mayhem(self) -> None:
        self.assertEqual(detect_mode(game_mode="KIWI").kind, "mayhem")
        self.assertEqual(detect_mode(queue_id=2400).label, "ARAM: Mayhem")
        self.assertEqual(detect_mode(queue_id=450, game_mode="KIWI").kind, "mayhem")

    def test_normal_aram_is_not_mayhem(self) -> None:
        info = detect_mode(game_mode="ARAM", queue_id=450)
        self.assertEqual(info.kind, "aram")
        self.assertFalse(info.mayhem_shop)

    def test_bridge_map_without_a_signal_is_unconfirmed(self) -> None:
        info = detect_mode(game_mode="CLASSIC", map_name="Map12")
        self.assertEqual(info.kind, "aram-unconfirmed")
        self.assertTrue(info.bridge)
        self.assertFalse(info.mayhem_shop)

    def test_classic_without_a_bridge_map_stays_rift(self) -> None:
        self.assertEqual(detect_mode(game_mode="CLASSIC", map_name="Map11").kind, "rift")

    def test_gameflow_queue(self) -> None:
        body = {"gameData": {"queue": {"id": 2400, "name": "ARAM: Mayhem"}}}
        self.assertEqual(queue_id_from_gameflow(body), 2400)
        self.assertIsNone(queue_id_from_gameflow({}))


class ShopTests(unittest.TestCase):
    def test_mayhem_does_not_use_the_rift_boot_path(self) -> None:
        catalog = bridge_catalog()
        rift = {buy.completed_id for buy in recommend(AHRI, ASSASSINS, {}, 2000, catalog.items)}
        view, _interval = build_view(LiveResult("ok", game("KIWI")), LcuResult.down(), catalog)
        text = buy_text(view)
        self.assertIn(3047, rift)
        self.assertIn("Zhonya", text)
        self.assertIn("Rite of Ruin", text)
        self.assertNotIn("Steelcaps", text)
        self.assertNotIn("Dead Man", text)
        self.assertEqual(view.headline, "In game · ARAM: Mayhem")
        self.assertIn("fountain", view.note.lower())
        self.assertIn("not in the live client", view.ingame.detail_line.lower())

    def test_normal_aram_skips_mayhem_legendaries(self) -> None:
        catalog = bridge_catalog()
        view, _interval = build_view(LiveResult("ok", game("ARAM")), LcuResult.down(), catalog)
        text = buy_text(view)
        self.assertEqual(view.headline, "In game · ARAM")
        self.assertIn("Zhonya", text)
        self.assertNotIn("Rite of Ruin", text)
        self.assertNotIn("Steelcaps", text)
        self.assertIn("not Summoner's Rift", view.note)

    def test_unconfirmed_map_says_so_and_stays_off_rift(self) -> None:
        catalog = bridge_catalog()
        view, _interval = build_view(
            LiveResult("ok", game("CLASSIC", map_name="Howling Abyss")),
            LcuResult.down(),
            catalog,
        )
        text = buy_text(view)
        self.assertIn("Could not tell ARAM: Mayhem", view.note)
        self.assertNotIn("Summoner's Rift", view.headline)
        self.assertIn("Zhonya", text)
        self.assertNotIn("Rite of Ruin", text)
        self.assertNotIn("Steelcaps", text)

    def test_grievous_augment_skips_a_second_antiheal_item(self) -> None:
        catalog = bridge_catalog()
        payload = game("KIWI", augments=["Grievous Wounds"])
        payload["allPlayers"][1]["championName"] = "Soraka"
        payload["allPlayers"][2]["championName"] = "Xerath"
        payload["allPlayers"][3]["championName"] = "Ziggs"
        payload["allPlayers"][4]["championName"] = "Brand"
        payload["allPlayers"][5]["championName"] = "Jinx"
        view, _interval = build_view(LiveResult("ok", payload), LcuResult.down(), catalog)
        self.assertNotIn("Morellonomicon", buy_text(view))
        self.assertIn("Grievous Wounds", view.ingame.detail_line)
        self.assertIn("Skipped another grievous-wounds item", view.ingame.detail_line)

    def test_attack_damage_inventory_does_not_buy_an_ability_power_legendary(self) -> None:
        kennen = champ(85, "Kennen", "Kennen", ["Mage", "Marksman"], 6, 7, 4)
        base = bridge_catalog()
        items = dict(base.items)
        items[6672] = shop_item(6672, "Kraken Slayer", 3000, tags=("Damage", "AttackSpeed"))
        items[3094] = shop_item(3094, "Rapid Firecannon", 2600, tags=("Damage", "CriticalStrike", "AttackSpeed"))
        items[3033] = shop_item(3033, "Mortal Reminder", 3000)
        catalog = DragonData("test", [*base.by_key.values(), kennen], items)
        payload = game("KIWI")
        payload["allPlayers"][0]["championName"] = "Kennen"
        payload["allPlayers"][0]["items"] = [
            {"itemID": 6672, "count": 1},
            {"itemID": 3094, "count": 1},
        ]
        payload["allPlayers"][1]["championName"] = "Soraka"
        view, _interval = build_view(LiveResult("ok", payload), LcuResult.down(), catalog)
        text = buy_text(view)
        self.assertIn("Mortal Reminder", text)
        self.assertNotIn("Rite of Ruin", text)
        self.assertNotIn("Morellonomicon", text)

    def test_queue_id_on_the_lobby_labels_mayhem_during_select(self) -> None:
        catalog = bridge_catalog()
        select = ChampSelect(
            allies=[222],
            enemies=[238, 91, 122],
            bans=[],
            pickable=[54, 103],
            position="",
            local_champion_id=103,
            rerolls_remaining=2,
        )
        view, _interval = build_view(LiveResult.down(), LcuResult("champselect", select, queue_id=2400), catalog)
        self.assertEqual(view.headline, "Champion select · ARAM: Mayhem")
        self.assertIn("Malphite", view.picks.pick_line)
        self.assertIn("bench", view.picks.pick_line.lower())
        self.assertIn("rerolls left: 2", view.picks.meta_line)


class RerollTests(unittest.TestCase):
    def test_session_keeps_rerolls_and_bench(self) -> None:
        session = {
            "localPlayerCellId": 0,
            "rerollsRemaining": 1,
            "myTeam": [{"cellId": 0, "championId": 16, "assignedPosition": ""}],
            "theirTeam": [],
            "bans": {},
            "benchChampions": [{"championId": 54}],
            "actions": [],
        }
        parsed = parse_session(session, [16, 54, 103])
        self.assertEqual(parsed.rerolls_remaining, 1)
        self.assertEqual(parsed.local_champion_id, 16)
        self.assertIn(54, parsed.pickable or [])

    def test_poor_bridge_fit_with_rerolls_says_reroll(self) -> None:
        catalog = bridge_catalog()
        select = ChampSelect(
            allies=[],
            enemies=[122, 122, 122, 122, 122],
            pickable=[16],
            local_champion_id=16,
            rerolls_remaining=1,
        )
        view, _interval = build_view(LiveResult.down(), LcuResult("champselect", select, queue_id=2400), catalog)
        self.assertTrue(view.picks.pick_line.startswith("Reroll"))
        self.assertIn("Soraka", view.picks.pick_line)

    def test_rift_select_still_uses_the_lane(self) -> None:
        catalog = bridge_catalog()
        select = ChampSelect(
            allies=[222],
            enemies=[238, 91, 122],
            pickable=[54, 103],
            position="top",
        )
        view, _interval = build_view(LiveResult.down(), LcuResult("champselect", select), catalog)
        self.assertEqual(view.headline, "Champion select · Summoner's Rift")
        self.assertIn("Malphite", view.picks.pick_line)
        self.assertNotIn("Reroll", view.picks.pick_line)


if __name__ == "__main__":
    unittest.main()
