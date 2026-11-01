"""Offline tests for shop advice, champion select, and the waiting state."""

from __future__ import annotations

import unittest
from pathlib import Path

from league_overlay.catalog import DragonData
from league_overlay.items import frontier_buys, next_purchase, recommend
from league_overlay.lcu import ChampSelect, LcuResult, parse_lockfile, parse_session
from league_overlay.live import LiveResult, match_player
from league_overlay.model import Champion, Item
from league_overlay.picks import suggest
from league_overlay.roles import roles_for
from league_overlay.threats import build_profile, damage_type, summarize
from league_overlay.view import ACTIVE_INTERVAL, IDLE_INTERVAL, build_view
from league_overlay.winutil import WS_EX_LAYERED, WS_EX_TRANSPARENT, style_with_clickthrough

ROOT = Path(__file__).resolve().parents[1]


def champ(key: int, champ_id: str, name: str, tags: list[str], attack: int, magic: int, defense: int) -> Champion:
    return Champion(key, champ_id, name, tuple(tags), attack, magic, defense)


def item(
    item_id: int,
    name: str,
    total: int,
    base: int | None = None,
    from_ids: tuple[int, ...] = (),
    tags: tuple[str, ...] = (),
) -> Item:
    return Item(
        id=item_id,
        name=name,
        total=total,
        base=total if base is None else base,
        purchasable=True,
        summoners_rift=True,
        in_store=True,
        tags=tags,
        from_ids=from_ids,
        required_champion="",
    )


AHRI = champ(103, "Ahri", "Ahri", ["Mage", "Assassin"], 3, 8, 4)
JINX = champ(222, "Jinx", "Jinx", ["Marksman"], 9, 4, 2)
ZED = champ(238, "Zed", "Zed", ["Assassin"], 9, 1, 2)
TALON = champ(91, "Talon", "Talon", ["Assassin"], 9, 1, 3)
QIYANA = champ(246, "Qiyana", "Qiyana", ["Assassin"], 0, 4, 2)
NAAFIRI = champ(950, "Naafiri", "Naafiri", ["Assassin", "Fighter"], 9, 0, 5)
RENGAR = champ(107, "Rengar", "Rengar", ["Assassin", "Fighter"], 7, 2, 4)
SORAKA = champ(16, "Soraka", "Soraka", ["Support", "Mage"], 2, 7, 5)
DARIUS = champ(122, "Darius", "Darius", ["Fighter", "Tank"], 9, 1, 5)
LEE = champ(64, "LeeSin", "Lee Sin", ["Fighter", "Assassin"], 8, 3, 5)
MALPHITE = champ(54, "Malphite", "Malphite", ["Tank", "Mage"], 5, 7, 9)
GAREN = champ(86, "Garen", "Garen", ["Fighter", "Tank"], 7, 1, 7)
SYNDRA = champ(134, "Syndra", "Syndra", ["Mage"], 2, 9, 3)
ORIANNA = champ(61, "Orianna", "Orianna", ["Mage", "Support"], 4, 9, 3)
AZIR = champ(268, "Azir", "Azir", ["Mage", "Marksman"], 6, 8, 3)
ZIGGS = champ(115, "Ziggs", "Ziggs", ["Mage"], 2, 9, 4)
BRAND = champ(63, "Brand", "Brand", ["Mage", "Support"], 2, 9, 2)
YUUMI = champ(350, "Yuumi", "Yuumi", ["Support", "Mage"], 5, 8, 1)
GWEN = champ(887, "Gwen", "Gwen", ["Fighter"], 7, 5, 4)
BELVETH = champ(200, "Belveth", "Bel'Veth", ["Fighter"], 4, 7, 2)
FIZZ = champ(105, "Fizz", "Fizz", ["Assassin", "Fighter"], 6, 7, 4)
NILAH = champ(895, "Nilah", "Nilah", ["Fighter", "Assassin"], 8, 4, 4)
JAYCE = champ(126, "Jayce", "Jayce", ["Fighter", "Marksman"], 8, 3, 4)
BRAUM = champ(201, "Braum", "Braum", ["Tank", "Support"], 3, 4, 9)


def shop(*items: Item) -> dict[int, Item]:
    return {entry.id: entry for entry in items}


class ThreatTests(unittest.TestCase):
    def test_damage_overrides_and_profiles(self) -> None:
        self.assertEqual(damage_type(QIYANA), "ad")
        self.assertEqual(damage_type(BELVETH), "ad")
        self.assertEqual(damage_type(GWEN), "ap")
        self.assertEqual(build_profile(AHRI), "Mage")
        self.assertEqual(build_profile(JINX), "Marksman")
        self.assertEqual(build_profile(MALPHITE), "Tank")
        self.assertEqual(build_profile(SORAKA), "Support")
        self.assertEqual(build_profile(YUUMI), "Support")
        self.assertEqual(build_profile(GWEN), "Battlemage")
        self.assertEqual(build_profile(BELVETH), "Fighter")
        self.assertEqual(build_profile(ZED), "Assassin")
        self.assertEqual(build_profile(FIZZ), "Mage")
        self.assertEqual(build_profile(NILAH), "Marksman")
        self.assertEqual(build_profile(JAYCE), "Fighter")

    def test_soraka_is_heal_and_braum_is_not_a_mage_carry(self) -> None:
        threats = summarize([SORAKA, BRAUM, JINX])
        self.assertGreaterEqual(threats.heal, 1)
        self.assertIn("Soraka", threats.names["heal"])
        self.assertLess(threats.ap, 1.5)
        self.assertGreaterEqual(threats.ad, 1)
        self.assertGreaterEqual(threats.tank, 1)

    def test_roles(self) -> None:
        self.assertIn("bottom", roles_for("Jinx") or ())
        self.assertIn("jungle", roles_for("LeeSin") or ())
        self.assertIn("middle", roles_for("Ahri") or ())
        self.assertIn("utility", roles_for("Thresh") or ())
        self.assertIn("top", roles_for("Malphite") or ())
        self.assertIsNone(roles_for("Locke"))


class ItemTests(unittest.TestCase):
    def test_thornmail_component_order(self) -> None:
        items = shop(
            item(1029, "Cloth Armor", 300),
            item(1028, "Ruby Crystal", 400),
            item(1031, "Chain Vest", 800, 500, (1029,)),
            item(3076, "Bramble Vest", 800, 200, (1029, 1029), ("Armor",)),
            item(3075, "Thornmail", 2450, 450, (3076, 1031, 1028), ("Health", "Armor")),
        )
        self.assertEqual(next_purchase(3075, {}, 1000, items), (1029, 300, False))
        self.assertEqual(next_purchase(3075, {1029: 2}, 1000, items), (3076, 200, True))
        self.assertEqual(next_purchase(3075, {3076: 1, 1031: 1, 1028: 1}, 500, items), (3075, 450, True))
        self.assertIsNone(next_purchase(3075, {3075: 1}, 5000, items))
        self.assertIn(1029, frontier_buys(3075, {}, items))

    def test_mage_into_ad_assassins_buys_zhonya_and_steelcaps(self) -> None:
        items = shop(
            item(3157, "Zhonya's Hourglass", 3250, tags=("Armor", "SpellDamage")),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
            item(3111, "Mercury's Treads", 1250, tags=("SpellBlock", "Boots")),
            item(3102, "Banshee's Veil", 3000, tags=("SpellBlock", "SpellDamage")),
        )
        enemies = [ZED, TALON, QIYANA, NAAFIRI, RENGAR]
        buys = recommend(AHRI, enemies, {}, 400, items)
        completed = {buy.completed_id for buy in buys}
        self.assertIn(3157, completed)
        self.assertIn(3047, completed)
        zhonya = next(buy for buy in buys if buy.completed_id == 3157)
        self.assertIn("burst", zhonya.why)
        self.assertFalse(zhonya.affordable)

    def test_marksman_into_healing_buys_mortal_reminder(self) -> None:
        items = shop(
            item(3033, "Mortal Reminder", 3000, tags=("Damage", "ArmorPenetration")),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
            item(3036, "Lord Dominik's Regards", 3300, tags=("Damage", "ArmorPenetration")),
        )
        buys = recommend(JINX, [SORAKA, JINX, ZED, DARIUS, LEE], {}, 900, items)
        self.assertIn(3033, {buy.completed_id for buy in buys})

    def test_tank_into_magic_buys_resist(self) -> None:
        items = shop(
            item(3111, "Mercury's Treads", 1250, tags=("SpellBlock", "Boots")),
            item(4401, "Force of Nature", 2800, tags=("Health", "SpellBlock")),
            item(2504, "Kaenic Rookern", 2900, tags=("Health", "SpellBlock")),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
        )
        enemies = [SYNDRA, ORIANNA, AZIR, ZIGGS, BRAND]
        buys = recommend(MALPHITE, enemies, {}, 2000, items)
        completed = {buy.completed_id for buy in buys}
        self.assertIn(3111, completed)
        self.assertTrue(completed & {4401, 2504})

    def test_owned_grievous_is_not_recommended_again(self) -> None:
        items = shop(
            item(3075, "Thornmail", 2450, tags=("Health", "Armor")),
            item(3742, "Dead Man's Plate", 2900, tags=("Health", "Armor")),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
        )
        buys = recommend(MALPHITE, [DARIUS, LEE, JINX, ZED, SORAKA], {3075: 1}, 2000, items)
        self.assertNotIn(3075, {buy.completed_id for buy in buys})

    def test_existing_boots_are_not_replaced(self) -> None:
        items = shop(
            item(1001, "Boots", 300, tags=("Boots",)),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
            item(3742, "Dead Man's Plate", 2900, tags=("Health", "Armor")),
        )
        buys = recommend(champ(122, "Darius", "Darius", ["Fighter", "Tank"], 9, 1, 5), [JINX, ZED, LEE, DARIUS, TALON], {1001: 1}, 3000, items)
        self.assertNotIn(3047, {buy.completed_id for buy in buys})
        self.assertTrue(buys)


class PickTests(unittest.TestCase):
    def test_top_into_ad_team_suggests_malphite_from_owned(self) -> None:
        catalog = DragonData("test", [AHRI, MALPHITE, GAREN, JINX, ZED, TALON, QIYANA, DARIUS, LEE], {})
        suggestion = suggest(
            [103, 54, 86],
            [JINX],
            [ZED, TALON, QIYANA, DARIUS, LEE],
            bans={157},
            position="top",
            catalog=catalog,
            taken_ids={222, 238, 91, 246, 122, 64, 157},
        )
        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertEqual(suggestion.champion.id, "Malphite")
        self.assertIn("armor", suggestion.why.lower())
        self.assertEqual(suggestion.alternatives[0], "Garen")

    def test_banned_and_ally_champions_are_excluded(self) -> None:
        catalog = DragonData("test", [AHRI, MALPHITE, JINX], {})
        suggestion = suggest([54, 103, 222], [JINX], [], set(), "bottom", catalog, taken_ids={222})
        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertNotEqual(suggestion.champion.id, "Jinx")


class SourceTests(unittest.TestCase):
    def test_lockfile_round_trip_hides_password(self) -> None:
        lock = parse_lockfile("LeagueClient:10:2999:se:cret:https\n")
        self.assertEqual(lock.password, "se:cret")
        self.assertEqual(lock.port, 2999)
        self.assertNotIn("se:cret", repr(lock))
        with self.assertRaises(ValueError):
            parse_lockfile("nope")

    def test_session_parses_role_bans_and_bench(self) -> None:
        session = {
            "localPlayerCellId": 1,
            "myTeam": [
                {"cellId": 0, "championId": 222, "assignedPosition": "bottom"},
                {"cellId": 1, "championId": 0, "assignedPosition": "top"},
            ],
            "theirTeam": [{"championId": 238}, {"championId": 0}],
            "bans": {"myTeamBans": [157], "theirTeamBans": []},
            "actions": [[{"actorCellId": 1, "type": "ban", "championId": 157, "completed": True}]],
            "benchChampions": [{"championId": 54}, {"championId": 103}],
        }
        parsed = parse_session(session, None)
        self.assertEqual(parsed.position, "top")
        self.assertEqual(parsed.allies, [222])
        self.assertEqual(parsed.enemies, [238])
        self.assertIn(157, parsed.bans)
        self.assertEqual(parsed.pickable, [54, 103])

    def test_match_player_by_riot_id(self) -> None:
        active = {"riotId": "Sal#NA1", "currentGold": 10}
        players = [
            {"summonerName": "Other", "championName": "Zed"},
            {"riotIdGameName": "Sal", "championName": "Ahri"},
        ]
        me = match_player(active, players)
        self.assertIsNotNone(me)
        assert me is not None
        self.assertEqual(me["championName"], "Ahri")


class ViewTests(unittest.TestCase):
    def test_waiting_for_league_when_nothing_is_running(self) -> None:
        view, interval = build_view(LiveResult.down(), LcuResult.down(), DragonData.empty())
        self.assertEqual(view.headline, "Waiting for League")
        self.assertEqual(view.ingame.message, "No active game.")
        self.assertEqual(view.picks.message, "Champion select is unavailable.")
        self.assertEqual(interval, IDLE_INTERVAL)
        self.assertIn("not cached", view.warning)

    def test_ingame_still_runs_when_champ_select_is_down(self) -> None:
        catalog = DragonData(
            "test",
            [AHRI, ZED, TALON, QIYANA, NAAFIRI, RENGAR],
            shop(
                item(3157, "Zhonya's Hourglass", 3250),
                item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
            ),
        )
        payload = {
            "activePlayer": {"summonerName": "Sal", "riotId": "Sal#NA1", "currentGold": 400},
            "allPlayers": [
                {"summonerName": "Sal", "riotId": "Sal#NA1", "championName": "Ahri", "team": "ORDER", "items": []},
                {"summonerName": "a", "championName": "Zed", "team": "CHAOS", "items": []},
                {"summonerName": "b", "championName": "Talon", "team": "CHAOS", "items": []},
                {"summonerName": "c", "championName": "Qiyana", "team": "CHAOS", "items": []},
                {"summonerName": "d", "championName": "Naafiri", "team": "CHAOS", "items": []},
                {"summonerName": "e", "championName": "Rengar", "team": "CHAOS", "items": []},
            ],
            "gameData": {"gameTime": 754, "gameMode": "CLASSIC"},
        }
        view, interval = build_view(LiveResult("ok", payload), LcuResult.down(), catalog)
        self.assertEqual(view.headline, "In game")
        self.assertEqual(view.picks.message, "Champion select is unavailable.")
        self.assertEqual(interval, ACTIVE_INTERVAL)
        text = " ".join(buy.item_line + buy.why for buy in view.ingame.buys)
        self.assertIn("Zhonya", text)
        self.assertIn("Ahri", view.ingame.champion_line)
        self.assertIn("400g", view.ingame.champion_line)

    def test_champ_select_panel(self) -> None:
        catalog = DragonData("test", [AHRI, MALPHITE, JINX, ZED, TALON, DARIUS], {})
        select = ChampSelect(
            allies=[222],
            enemies=[238, 91, 122],
            bans=[],
            pickable=[54, 103],
            position="top",
        )
        view, interval = build_view(LiveResult.down(), LcuResult("champselect", select), catalog)
        self.assertEqual(view.headline, "Champion select")
        self.assertIn("Malphite", view.picks.pick_line)
        self.assertEqual(view.ingame.message, "No active game.")
        self.assertEqual(interval, ACTIVE_INTERVAL)

    def test_clickthrough_style_bits(self) -> None:
        base = 0x00000100
        enabled = style_with_clickthrough(base, True)
        self.assertTrue(enabled & WS_EX_TRANSPARENT)
        self.assertTrue(enabled & WS_EX_LAYERED)
        disabled = style_with_clickthrough(enabled, False)
        self.assertFalse(disabled & WS_EX_TRANSPARENT)
        self.assertTrue(disabled & WS_EX_LAYERED)
        self.assertTrue(disabled & base)

    def test_readme_matches_the_app(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        heuristic = (ROOT / "HEURISTIC.md").read_text(encoding="utf-8")
        self.assertIn("py -m league_overlay", readme)
        self.assertIn("Ctrl+Shift+O", readme)
        self.assertIn("Ctrl+Shift+H", readme)
        self.assertIn("this same PC", readme)
        self.assertIn("Waiting for League", readme)
        self.assertIn("Champion select is unavailable", readme)
        self.assertIn("win rate", heuristic.lower())


if __name__ == "__main__":
    unittest.main()
