"""Offline tests for shop advice, champion select, and the waiting state."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from league_overlay.bridge import recommend_bridge
from league_overlay.catalog import DragonData, parse_items
from league_overlay.items import (
    advise,
    choose_sell,
    completion_blocked,
    enemy_build_line,
    frontier_buys,
    next_purchase,
    recommend,
)
from league_overlay.lcu import ChampSelect, LcuResult, parse_lockfile, parse_session
from league_overlay.live import LiveResult, match_player, parse_game
from league_overlay.threats import Threats
from league_overlay.model import Champion, Item
from league_overlay.picks import suggest
from league_overlay.roles import roles_for
from league_overlay.threats import build_profile, champion_kit, damage_type, summarize
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
    *,
    abyss: bool = False,
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
        howling_abyss=abyss,
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

    def test_mage_plan_is_spell_items(self) -> None:
        items = shop(
            item(3020, "Sorcerer's Shoes", 1100, tags=("Boots", "MagicPenetration")),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
            item(3089, "Rabadon's Deathcap", 3500, tags=("SpellDamage",)),
            item(6655, "Luden's Echo", 2750, tags=("SpellDamage",)),
            item(4645, "Shadowflame", 3200, tags=("SpellDamage",)),
            item(3157, "Zhonya's Hourglass", 3250, tags=("Armor", "SpellDamage")),
            item(3102, "Banshee's Veil", 3000, tags=("SpellBlock", "SpellDamage")),
            item(3031, "Infinity Edge", 3500, tags=("Damage", "CriticalStrike")),
            item(3072, "Bloodthirster", 3400, tags=("Damage", "LifeSteal")),
        )
        result = advise(AHRI, [ZED, TALON, QIYANA, NAAFIRI, RENGAR], {}, 5000, items)
        self.assertEqual(len(result.plan), 6)
        self.assertNotIn("Infinity Edge", result.plan)
        self.assertNotIn("Bloodthirster", result.plan)
        self.assertIn("Zhonya's Hourglass", result.plan)
        self.assertTrue({"Luden's Echo", "Rabadon's Deathcap", "Shadowflame"} & set(result.plan))
        self.assertEqual(result.focus, "ability power on spells")

    def test_marksman_plan_is_attack_damage(self) -> None:
        items = shop(
            item(3006, "Berserker's Greaves", 1100, tags=("Boots", "AttackSpeed")),
            item(3111, "Mercury's Treads", 1250, tags=("Boots", "SpellBlock")),
            item(3031, "Infinity Edge", 3500, tags=("Damage", "CriticalStrike")),
            item(3094, "Rapid Firecannon", 2650, tags=("Damage", "CriticalStrike", "AttackSpeed")),
            item(3046, "Phantom Dancer", 2650, tags=("Damage", "CriticalStrike", "AttackSpeed")),
            item(3072, "Bloodthirster", 3400, tags=("Damage", "LifeSteal")),
            item(3156, "Maw of Malmortius", 3100, tags=("SpellBlock", "Damage")),
            item(3089, "Rabadon's Deathcap", 3500, tags=("SpellDamage",)),
            item(6653, "Liandry's Torment", 3000, tags=("Health", "SpellDamage")),
        )
        result = advise(JINX, [SYNDRA, ORIANNA, AZIR, ZIGGS, BRAND], {}, 5000, items)
        self.assertEqual(len(result.plan), 6)
        self.assertNotIn("Rabadon's Deathcap", result.plan)
        self.assertNotIn("Liandry's Torment", result.plan)
        self.assertIn("Infinity Edge", result.plan)
        self.assertEqual(result.focus, "attack damage on auto attacks")

    def test_jhin_scales_with_crit_damage_not_attack_speed(self) -> None:
        jhin = champ(202, "Jhin", "Jhin", ["Marksman"], 9, 2, 2)
        items = shop(
            item(3031, "Infinity Edge", 3500, tags=("Damage", "CriticalStrike"), abyss=True),
            item(6676, "The Collector", 3000, tags=("Damage", "CriticalStrike", "ArmorPenetration"), abyss=True),
            item(3094, "Rapid Firecannon", 2650, tags=("CriticalStrike", "AttackSpeed"), abyss=True),
            item(3046, "Phantom Dancer", 2650, tags=("CriticalStrike", "AttackSpeed"), abyss=True),
            item(6672, "Kraken Slayer", 3000, tags=("Damage", "AttackSpeed"), abyss=True),
            item(3072, "Bloodthirster", 3400, tags=("Damage", "LifeSteal"), abyss=True),
            item(3156, "Maw of Malmortius", 3100, tags=("SpellBlock", "Damage", "LifeSteal"), abyss=True),
            item(3139, "Mercurial Scimitar", 3200, tags=("SpellBlock", "Damage", "LifeSteal"), abyss=True),
            item(3033, "Mortal Reminder", 3000, tags=("Damage", "ArmorPenetration"), abyss=True),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots"), abyss=True),
            item(3111, "Mercury's Treads", 1250, tags=("Boots", "SpellBlock"), abyss=True),
        )
        enemies = [SYNDRA, ORIANNA, MALPHITE, SORAKA, ZED]
        owned = {3033: 1}
        result = advise(jhin, enemies, owned, 1600, items)
        self.assertIn("Infinity Edge", result.plan)
        self.assertIn("The Collector", result.plan)
        self.assertNotIn("Phantom Dancer", result.plan)
        self.assertNotIn("Kraken Slayer", result.plan)
        resist = [name for name in result.plan if name in {"Maw of Malmortius", "Mercurial Scimitar"}]
        self.assertLessEqual(len(resist), 1)
        self.assertIn(result.buys[0].completed_name, {"Infinity Edge", "The Collector"})
        self.assertIn("crit", result.focus)
        bridge = recommend_bridge(jhin, enemies, owned, 1600, items, mayhem_shop=True)
        self.assertIn("Infinity Edge", bridge.plan)
        self.assertIn("The Collector", bridge.plan)
        self.assertNotIn("Phantom Dancer", bridge.plan)
        self.assertIn(bridge.buys[0].completed_name, {"Infinity Edge", "The Collector"})

    def test_a_support_tag_does_not_make_a_damage_mage_an_enchanter(self) -> None:
        mages = (
            champ(26, "Zilean", "Zilean", ["Support", "Mage"], 2, 8, 5),
            champ(74, "Heimerdinger", "Heimerdinger", ["Mage", "Support"], 2, 8, 6),
            champ(163, "Taliyah", "Taliyah", ["Mage", "Support"], 1, 8, 7),
            champ(25, "Morgana", "Morgana", ["Support", "Mage"], 1, 8, 6),
            champ(43, "Karma", "Karma", ["Mage", "Support"], 1, 8, 7),
            champ(497, "Rakan", "Rakan", ["Support"], 2, 8, 4),
            champ(432, "Bard", "Bard", ["Support", "Mage"], 4, 5, 4),
        )
        for mage in mages:
            self.assertEqual(build_profile(mage), "Mage", mage.name)
            self.assertEqual(champion_kit(mage).role, "Mage", mage.name)
        self.assertEqual(champion_kit(SORAKA).role, "Enchanter")
        self.assertEqual(champion_kit(YUUMI).role, "Enchanter")
        zilean = mages[0]
        items = shop(
            item(6617, "Moonstone Renewer", 2200, tags=("Health", "SpellDamage"), abyss=True),
            item(3107, "Redemption", 2300, tags=("Health",), abyss=True),
            item(6616, "Staff of Flowing Water", 2250, tags=("SpellDamage", "AbilityHaste"), abyss=True),
            item(3089, "Rabadon's Deathcap", 3500, tags=("SpellDamage",), abyss=True),
            item(6655, "Luden's Echo", 2750, tags=("SpellDamage", "AbilityHaste", "CooldownReduction"), abyss=True),
            item(4629, "Cosmic Drive", 3000, tags=("Health", "SpellDamage", "AbilityHaste"), abyss=True),
            item(3157, "Zhonya's Hourglass", 3250, tags=("Armor", "SpellDamage"), abyss=True),
            item(3165, "Morellonomicon", 2950, tags=("Health", "SpellDamage", "AbilityHaste"), abyss=True),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots"), abyss=True),
            item(3020, "Sorcerer's Shoes", 1100, tags=("Boots", "MagicPenetration"), abyss=True),
            item(4005, "Imperial Mandate", 2300, tags=("SpellDamage", "ManaRegen", "AbilityHaste"), abyss=True),
        )
        enemies = [JINX, ZED, SYNDRA, ORIANNA, MALPHITE]
        result = advise(zilean, enemies, {}, 4000, items)
        for name in ("Moonstone Renewer", "Redemption", "Staff of Flowing Water"):
            self.assertNotIn(name, result.plan)
        self.assertIn("Rabadon's Deathcap", result.plan)
        self.assertIn("Luden's Echo", result.plan)
        self.assertIn("bombs", result.focus)
        bridge = recommend_bridge(zilean, enemies, {}, 4000, items, mayhem_shop=True)
        self.assertNotIn("Moonstone Renewer", bridge.plan)
        self.assertIn("Rabadon's Deathcap", bridge.plan)
        self.assertIn("Luden's Echo", bridge.plan)
        owned = {3157: 1, 3107: 1, 6616: 1, 6617: 1, 3165: 1, 4005: 1}
        full = recommend_bridge(zilean, enemies, owned, 0, items, mayhem_shop=True, inventory_full=True)
        self.assertIn(full.buys[0].sell_name, {"Moonstone Renewer", "Redemption", "Staff of Flowing Water", "Imperial Mandate"})
        self.assertIn("does not fit", full.buys[0].sell_why)

    def test_tank_plan_stays_defensive_against_squishy_mages(self) -> None:
        items = shop(
            item(3111, "Mercury's Treads", 1250, tags=("Boots", "SpellBlock")),
            item(3047, "Plated Steelcaps", 1200, tags=("Armor", "Boots")),
            item(4401, "Force of Nature", 2800, tags=("Health", "SpellBlock")),
            item(2504, "Kaenic Rookern", 2900, tags=("Health", "SpellBlock")),
            item(3068, "Sunfire Aegis", 2800, tags=("Health", "Armor")),
            item(6664, "Hollow Radiance", 2800, tags=("Health", "SpellBlock")),
            item(3083, "Warmog's Armor", 3100, tags=("Health",)),
            item(3031, "Infinity Edge", 3500, tags=("Damage", "CriticalStrike")),
            item(3089, "Rabadon's Deathcap", 3500, tags=("SpellDamage",)),
            item(3074, "Ravenous Hydra", 3300, tags=("Damage", "LifeSteal")),
        )
        result = advise(MALPHITE, [SYNDRA, ORIANNA, AZIR, ZIGGS, BRAND], {}, 5000, items)
        self.assertEqual(len(result.plan), 6)
        for name in ("Infinity Edge", "Rabadon's Deathcap", "Ravenous Hydra"):
            self.assertNotIn(name, result.plan)
        self.assertTrue(any(name in result.plan for name in ("Force of Nature", "Kaenic Rookern", "Hollow Radiance")))
        self.assertEqual(result.focus, "tank health and resists")

    def test_full_mage_inventory_sells_attack_damage_not_a_core(self) -> None:
        items = shop(
            item(3089, "Rabadon's Deathcap", 3500, tags=("SpellDamage",)),
            item(6655, "Luden's Echo", 2750, tags=("SpellDamage",)),
            item(4645, "Shadowflame", 3200, tags=("SpellDamage",)),
            item(4646, "Stormsurge", 2800, tags=("SpellDamage",)),
            item(3020, "Sorcerer's Shoes", 1100, tags=("Boots", "MagicPenetration")),
            item(3156, "Maw of Malmortius", 3100, tags=("SpellBlock", "Damage")),
            item(3157, "Zhonya's Hourglass", 3250, tags=("Armor", "SpellDamage")),
            item(3102, "Banshee's Veil", 3000, tags=("SpellBlock", "SpellDamage")),
        )
        owned = {3089: 1, 6655: 1, 4645: 1, 4646: 1, 3020: 1, 3156: 1}
        buys = recommend(AHRI, [SYNDRA, ORIANNA, AZIR, ZIGGS, BRAND], owned, 2000, items, inventory_full=True)
        self.assertTrue(buys)
        self.assertEqual(buys[0].sell_name, "Maw of Malmortius")
        self.assertNotEqual(buys[0].sell_id, 3089)
        self.assertNotIn(buys[0].completed_name, {"Maw of Malmortius", "Infinity Edge"})

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

    def test_last_whisper_upgrade_is_blocked_once_one_is_finished(self) -> None:
        items = shop(
            item(1036, "Long Sword", 350),
            item(3035, "Last Whisper", 1450, 750, from_ids=(1036, 1036)),
            item(3033, "Mortal Reminder", 3000, 500, from_ids=(3035,)),
            item(3036, "Lord Dominik's Regards", 3300, 600, from_ids=(3035, 6670)),
            item(6670, "Noonquiver", 1300),
        )
        self.assertTrue(completion_blocked(3036, {3033: 1}, items))
        self.assertFalse(completion_blocked(3036, {3035: 1}, items))
        step = next_purchase(3036, {3035: 1}, 2000, items)
        self.assertIsNotNone(step)
        assert step is not None
        self.assertNotEqual(step[0], 3035)
        self.assertEqual(step[0], 6670)

    def test_zhonya_is_not_treated_as_an_armor_stack(self) -> None:
        items = shop(
            item(3157, "Zhonya's Hourglass", 3250, tags=("Armor", "SpellDamage")),
            item(3143, "Randuin's Omen", 2700, tags=("Health", "Armor")),
        )
        self.assertEqual(enemy_build_line((("Ekko", (3157,)),), items), "")
        self.assertIn("armor on Zac", enemy_build_line((("Zac", (3143,)),), items))

    def test_cached_items_block_a_second_unique(self) -> None:
        path = ROOT / "cache" / "ddragon" / "item.json"
        if not path.is_file():
            self.skipTest("Data Dragon cache is not on this PC")
        items = parse_items(json.loads(path.read_text(encoding="utf-8")))
        self.assertTrue(completion_blocked(3036, {3033: 1}, items))
        self.assertTrue(completion_blocked(6694, {3033: 1}, items))
        self.assertTrue(completion_blocked(6673, {3156: 1}, items))
        self.assertTrue(completion_blocked(3047, {3158: 1}, items))
        self.assertFalse(completion_blocked(3036, {3035: 1}, items))
        self.assertFalse(completion_blocked(3158, {1001: 1}, items))
        self.assertTrue(completion_blocked(3040, {3042: 1}, items))
        self.assertTrue(completion_blocked(3003, {3042: 1}, items))
        step = next_purchase(3033, {3035: 1}, 5000, items)
        self.assertIsNotNone(step)
        assert step is not None
        self.assertNotEqual(step[0], 3035)


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
        self.assertEqual(view.headline, "In game · Summoner's Rift")
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
        self.assertEqual(view.headline, "Champion select · Summoner's Rift")
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


def _magic_threats() -> Threats:
    return Threats(
        ap=4.0,
        ad=0.3,
        names={
            "ad": [],
            "ap": ["Diana", "Maokai"],
            "tank": ["Maokai"],
            "heal": [],
            "attack_speed": [],
            "burst": ["Diana"],
            "mr": [],
            "shield": [],
        },
    )


class SellTests(unittest.TestCase):
    def _magic_shop(self) -> dict[int, Item]:
        return shop(
            item(3075, "Thornmail", 2450, tags=("Health", "Armor")),
            item(3020, "Sorcerer's Shoes", 1100, tags=("Boots", "MagicPenetration")),
            item(6655, "Luden's Echo", 2600, tags=("SpellDamage",)),
            item(6653, "Liandry's Torment", 3000, tags=("Health", "SpellDamage")),
            item(4646, "Stormsurge", 3200, tags=("SpellDamage",)),
            item(3102, "Banshee's Veil", 3000, tags=("SpellBlock", "SpellDamage")),
            item(3211, "Spectre's Cowl", 1250, tags=("Health", "SpellBlock")),
        )

    def test_full_inventory_sells_finished_armor_against_magic_damage(self) -> None:
        owned = {3075: 1, 3020: 1, 6655: 1, 6653: 1, 4646: 1, 3102: 1}
        choice = choose_sell(
            owned,
            self._magic_shop(),
            _magic_threats(),
            protected_ids=set(),
            locked_ids=set(),
            profile="Mage",
            enemy_builds=(("Maokai", (3211,)),),
            inventory_full=True,
            item_labels={3075: "Thornmail"},
        )
        self.assertIsNotNone(choice)
        assert choice is not None
        self.assertEqual(choice.item_id, 3075)
        self.assertEqual(choice.name, "Thornmail")
        self.assertIn("magic", choice.why)
        self.assertIn("Maokai stacked magic resist", choice.why)
        self.assertIn(choice.item_id, owned)

    def test_open_slot_has_no_sell(self) -> None:
        owned = {3075: 1, 3020: 1, 6655: 1, 6653: 1, 4646: 1, 3102: 1}
        self.assertIsNone(
            choose_sell(
                owned,
                self._magic_shop(),
                _magic_threats(),
                protected_ids=set(),
                locked_ids=set(),
                profile="Mage",
                inventory_full=False,
            )
        )

    def test_only_boots_are_never_sold(self) -> None:
        items = self._magic_shop()
        owned = {3075: 1, 3020: 1, 6655: 1, 6653: 1, 4646: 1, 3102: 1}
        choice = choose_sell(
            owned,
            items,
            _magic_threats(),
            protected_ids=set(),
            locked_ids={3075, 6655, 6653, 4646, 3102},
            profile="Mage",
            inventory_full=True,
        )
        self.assertIsNone(choice)

    def test_orphan_component_is_sold_before_a_finished_item(self) -> None:
        items = shop(
            item(3035, "Last Whisper", 1450, tags=("ArmorPenetration",)),
            item(3033, "Mortal Reminder", 3000, from_ids=(3035,), tags=("Damage", "ArmorPenetration")),
            item(3036, "Lord Dominik's Regards", 3300, from_ids=(3035,), tags=("Damage", "ArmorPenetration")),
            item(6694, "Serylda's Grudge", 3200, from_ids=(3035,), tags=("ArmorPenetration",)),
            item(3075, "Thornmail", 2450, tags=("Health", "Armor")),
            item(3020, "Sorcerer's Shoes", 1100, tags=("Boots",)),
            item(6655, "Luden's Echo", 2750, tags=("SpellDamage",)),
        )
        owned = {3035: 1, 3033: 1, 3075: 1, 3020: 1, 6655: 1, 4646: 1}
        items[4646] = item(4646, "Stormsurge", 2800, tags=("SpellDamage",))
        bare = choose_sell(
            owned,
            items,
            _magic_threats(),
            protected_ids=set(),
            locked_ids=set(),
            profile="Mage",
            inventory_full=True,
        )
        self.assertIsNotNone(bare)
        assert bare is not None
        self.assertEqual(bare.item_id, 3035)
        self.assertIn("no longer builds", bare.why)
        kept = choose_sell(
            owned,
            items,
            _magic_threats(),
            protected_ids={3035},
            locked_ids=set(),
            profile="Mage",
            inventory_full=True,
        )
        self.assertIsNotNone(kept)
        assert kept is not None
        self.assertEqual(kept.item_id, 3033)
        self.assertIn("attack damage", kept.why)
        self.assertNotEqual(kept.item_id, 3035)
        self.assertNotEqual(kept.item_id, 3020)
        self.assertIn(kept.item_id, owned)

    def test_weaker_duplicate_is_the_cheaper_copy(self) -> None:
        items = shop(
            item(6655, "Luden's Echo", 2600, tags=("SpellDamage",)),
            item(4646, "Stormsurge", 3200, tags=("SpellDamage",)),
            item(3020, "Sorcerer's Shoes", 1100, tags=("Boots",)),
        )
        choice = choose_sell(
            {6655: 1, 4646: 1, 3020: 1},
            items,
            _magic_threats(),
            protected_ids=set(),
            locked_ids=set(),
            profile="Mage",
            inventory_full=True,
        )
        self.assertIsNotNone(choice)
        assert choice is not None
        self.assertEqual(choice.item_id, 6655)
        self.assertIn("Stormsurge", choice.why)
        self.assertNotEqual(choice.item_id, 3020)

    def test_progress_toward_the_buy_is_not_sold(self) -> None:
        items = shop(
            item(3157, "Zhonya's Hourglass", 3250, from_ids=(1058,), tags=("Armor", "SpellDamage")),
            item(1058, "Needlessly Large Rod", 1250, tags=("Damage",)),
            item(3075, "Thornmail", 2450, tags=("Health", "Armor")),
            item(3020, "Sorcerer's Shoes", 1100, tags=("Boots", "MagicPenetration")),
            item(6655, "Luden's Echo", 2750, tags=("SpellDamage",)),
            item(3102, "Banshee's Veil", 3000, tags=("SpellBlock", "SpellDamage")),
            item(4646, "Stormsurge", 2800, tags=("SpellDamage",)),
        )
        owned = {1058: 1, 3075: 1, 3020: 1, 6655: 1, 3102: 1, 4646: 1}
        enemies = [ZED, TALON, QIYANA, NAAFIRI, RENGAR]
        buys = recommend(AHRI, enemies, owned, 400, items, inventory_full=True)
        self.assertTrue(buys)
        self.assertEqual(buys[0].completed_id, 3157)
        self.assertNotEqual(buys[0].sell_id, 1058)
        self.assertNotEqual(buys[0].sell_id, 3020)
        self.assertEqual(buys[0].sell_id, 3075)
        self.assertIn(buys[0].sell_id, owned)
        self.assertTrue(all(buy.sell_name == "" for buy in buys[1:]))
        open_slot = recommend(AHRI, enemies, owned, 400, items)
        self.assertEqual(open_slot[0].sell_name, "")


class SlotTests(unittest.TestCase):
    def _catalog(self) -> DragonData:
        return DragonData("test", [AHRI, ZED], shop(item(3157, "Zhonya's Hourglass", 3250)))

    def _payload(self, slots: list[dict]) -> dict:
        return {
            "activePlayer": {"summonerName": "Sal", "currentGold": 100},
            "allPlayers": [
                {"summonerName": "Sal", "championName": "Ahri", "team": "ORDER", "items": slots},
                {"summonerName": "a", "championName": "Zed", "team": "CHAOS", "items": []},
            ],
            "gameData": {"gameTime": 100, "gameMode": "CLASSIC"},
        }

    def test_trinket_slot_does_not_fill_the_inventory(self) -> None:
        slots = [
            {"itemID": 3157, "count": 1, "slot": index, "displayName": "Zhonya's Hourglass"}
            for index in range(5)
        ]
        slots.append({"itemID": 3340, "count": 1, "slot": 6, "displayName": "Stealth Ward"})
        game = parse_game(self._payload(slots), self._catalog())
        self.assertIsNotNone(game)
        assert game is not None
        self.assertEqual(game.item_slots, 5)
        self.assertNotIn(3340, game.owned)

    def test_potion_fills_a_slot_and_is_not_an_owned_sell_item(self) -> None:
        slots = [{"itemID": 3157, "count": 1, "slot": index} for index in range(5)]
        slots.append({"itemID": 2003, "count": 1, "slot": 5, "consumable": True, "displayName": "Health Potion"})
        game = parse_game(self._payload(slots), self._catalog())
        assert game is not None
        self.assertEqual(game.item_slots, 6)
        self.assertNotIn(2003, game.owned)
        self.assertEqual(game.owned[3157], 5)

    def test_trinket_placed_in_an_item_slot_counts(self) -> None:
        slots = [{"itemID": 3340, "count": 1, "slot": 2, "displayName": "Stealth Ward"}]
        game = parse_game(self._payload(slots), self._catalog())
        assert game is not None
        self.assertEqual(game.item_slots, 1)
        self.assertIn(3340, game.owned)

    def test_a_stack_is_one_slot(self) -> None:
        slots = [{"itemID": 1036, "count": 6, "slot": 0, "displayName": "Long Sword"}]
        game = parse_game(self._payload(slots), self._catalog())
        assert game is not None
        self.assertEqual(game.item_slots, 1)
        self.assertEqual(game.owned[1036], 6)


if __name__ == "__main__":
    unittest.main()
