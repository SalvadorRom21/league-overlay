"""Next shop step against the enemy team.

Completed items are a fixed list of Summoner's Rift answers (armor, magic
resist, grievous wounds, penetration, anti-burst). Names, prices, and the
component recipe come from Data Dragon at runtime. If a patch removes an item,
that rule is skipped. See HEURISTIC.md.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace

from league_overlay.model import Champion, Item
from league_overlay.threats import HEAL_CHAMPS, Kit, Threats, champion_factor, champion_kit, kit_focus, summarize

MIN_SCORE = 1.6
# The last slots of a six-item plan can sit under the counter cutoff.
# They still have to score, so a component with no finished item never fills a slot.
PLAN_FLOOR = 0.55
# Spare gold with the other five items finished. The boots swap waits for that moment.
HIGH_BOOT_GOLD = 2500
PLAN_SLOTS = 6
# Slots held for items his kit actually scales. The rest answer the enemy team.
CORE_SLOTS = 3

GRIEVOUS_IDS = {3075, 3033, 6609, 3165}
# Owning a component locks the shop path onto the item that builds from it.
COMPONENT_LOCK = {
    3076: {3075},  # Bramble Vest -> Thornmail
    3123: {3033, 6609},  # Executioner's Calling -> Mortal Reminder or Chempunk
    3916: {3165},  # Oblivion Orb -> Morellonomicon
}

TAG_WORD = {
    "ad": "physical damage",
    "ap": "magic damage",
    "tank": "tanks",
    "heal": "healing",
    "attack_speed": "attack speed",
    "burst": "burst",
    "mr": "magic resist",
    "shield": "shields",
}
LAST_WHISPER_ID = 3035
TEAR_ID = 3070
BASIC_BOOTS_ID = 1001

ALL = frozenset(
    {"Tank", "Fighter", "Assassin", "Marksman", "Mage", "Battlemage", "Support"}
)
AD_BRUISER = frozenset({"Fighter", "Assassin"})
AD_CARRY = frozenset({"Marksman", "Assassin"})
AP = frozenset({"Mage", "Battlemage", "Support"})
FRONT = frozenset({"Tank", "Fighter", "Support"})
TANKS = frozenset({"Tank", "Support"})


@dataclass(frozen=True)
class ItemRule:
    item_id: int
    profiles: frozenset[str]
    weights: tuple[tuple[str, float], ...]
    kind: str
    summary: str
    base: float = 0.0
    job: str = "answer"


RULES: tuple[ItemRule, ...] = (
    ItemRule(3047, ALL, (("ad", 1.35), ("attack_speed", 1.1)), "boots", "Armor boots", 0.15),
    ItemRule(3111, ALL, (("ap", 1.35), ("burst", 0.55)), "boots", "Magic resist boots and tenacity", 0.15),
    ItemRule(3020, AP, (), "boots", "Magic penetration boots for spells", 1.6),
    ItemRule(3006, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.2),), "boots", "Attack speed boots for auto attacks", 1.6),
    ItemRule(3158, frozenset({"Assassin", "Support"}), (), "boots", "Ability haste boots for spells", 1.5),
    ItemRule(
        3075,
        frozenset({"Tank", "Fighter", "Support"}),
        (("heal", 2.4), ("ad", 0.45)),
        "grievous",
        "Armor and grievous wounds",
    ),
    ItemRule(
        3033,
        frozenset({"Marksman"}),
        (("heal", 2.4), ("tank", 0.55)),
        "grievous",
        "Armor penetration and grievous wounds",
    ),
    ItemRule(
        6609,
        AD_BRUISER,
        (("heal", 2.4), ("ad", 0.25)),
        "grievous",
        "Attack damage and grievous wounds",
    ),
    ItemRule(3165, AP, (("heal", 2.4), ("ap", 0.2)), "grievous", "Ability power and grievous wounds"),
    ItemRule(
        3143,
        FRONT,
        (("attack_speed", 1.5), ("ad", 0.7)),
        "armor",
        "Armor, less crit damage, and an attack-speed slow",
    ),
    ItemRule(
        3110,
        frozenset({"Tank", "Fighter", "Support"}),
        (("attack_speed", 1.6), ("ad", 0.5)),
        "armor",
        "Armor and an attack-speed aura",
    ),
    ItemRule(3742, frozenset({"Tank", "Fighter"}), (("ad", 1.25),), "armor", "Armor and health"),
    ItemRule(
        6333,
        AD_BRUISER,
        (("ad", 1.15), ("burst", 0.45)),
        "armor",
        "Armor that delays physical damage",
    ),
    ItemRule(3068, frozenset({"Tank"}), (("ad", 1.05),), "armor", "Armor and a burn aura for a tank", 1.15, "core"),
    ItemRule(6662, frozenset({"Tank", "Fighter"}), (("ad", 1.05),), "armor", "Armor and a slow field"),
    ItemRule(2502, frozenset({"Tank"}), (("ad", 1.0),), "armor", "Armor and health"),
    ItemRule(
        3026,
        frozenset({"Marksman", "Assassin", "Fighter"}),
        (("burst", 1.3), ("ad", 0.45)),
        "anti_burst",
        "A revive against burst",
    ),
    ItemRule(4401, frozenset({"Tank", "Fighter", "Battlemage"}), (("ap", 1.45),), "mr", "Magic resist that stacks in combat"),
    ItemRule(
        2504,
        TANKS,
        (("ap", 1.15), ("burst", 0.7)),
        "mr",
        "A magic shield and high magic resist",
    ),
    ItemRule(3065, frozenset({"Tank", "Fighter", "Battlemage"}), (("ap", 1.05),), "mr", "Magic resist that boosts your healing"),
    ItemRule(6664, frozenset({"Tank"}), (("ap", 1.1),), "mr", "Magic resist and a burn aura for a tank", 1.15, "core"),
    ItemRule(8020, frozenset({"Tank", "Battlemage"}), (("ap", 1.15),), "mr", "Magic resist and nearby magic-damage amp"),
    ItemRule(
        3102,
        frozenset({"Mage", "Battlemage", "Support"}),
        (("ap", 1.0), ("burst", 1.05)),
        "mr",
        "A spell shield and magic resist",
    ),
    ItemRule(
        3156,
        frozenset({"Fighter", "Assassin", "Marksman"}),
        (("ap", 1.35), ("burst", 0.55)),
        "mr",
        "A magic shield on an attack-damage item",
    ),
    ItemRule(
        3091,
        frozenset({"Marksman", "Fighter"}),
        (("ap", 1.2), ("attack_speed", 0.25)),
        "mr",
        "Magic resist and attack speed",
    ),
    ItemRule(
        3139,
        frozenset({"Marksman", "Assassin"}),
        (("ap", 0.8), ("burst", 0.7)),
        "mr",
        "Magic resist and a cleanse",
    ),
    ItemRule(3036, frozenset({"Marksman"}), (("tank", 1.9),), "pen", "Armor penetration against high health"),
    ItemRule(3071, AD_BRUISER, (("tank", 1.6), ("ad", 0.2)), "pen", "Armor shred for physical damage"),
    ItemRule(
        3153,
        frozenset({"Marksman", "Fighter", "Assassin"}),
        (("tank", 1.7),),
        "pen",
        "Percent-health damage against tanks",
    ),
    ItemRule(3302, frozenset({"Marksman", "Fighter"}), (("tank", 1.5),), "pen", "Armor and magic penetration on-hit"),
    ItemRule(6694, AD_BRUISER, (("tank", 1.55),), "pen", "Armor penetration on abilities"),
    ItemRule(3135, AP, (("tank", 1.7), ("mr", 1.5)), "pen", "Magic penetration"),
    ItemRule(3137, AP, (("tank", 1.45), ("mr", 1.3)), "pen", "Magic penetration"),
    ItemRule(6653, AP, (("tank", 1.65), ("mr", 1.2)), "burn", "A max-health burn"),
    ItemRule(8010, frozenset({"Mage", "Battlemage"}), (("tank", 1.4), ("mr", 1.1)), "pen", "Magic resist shred"),
    ItemRule(
        3157,
        frozenset({"Mage", "Battlemage", "Support"}),
        (("burst", 1.45), ("ad", 0.7)),
        "anti_burst",
        "Stasis against burst",
    ),
    ItemRule(
        3053,
        frozenset({"Fighter", "Assassin"}),
        (("burst", 1.3), ("ad", 0.4)),
        "anti_burst",
        "A shield when you get low",
    ),
    ItemRule(
        6673,
        frozenset({"Marksman"}),
        (("burst", 1.35), ("ad", 0.35)),
        "anti_burst",
        "A shield against burst",
    ),
    ItemRule(3814, frozenset({"Assassin"}), (("burst", 1.25),), "anti_burst", "A spell shield on a lethality item"),
    ItemRule(
        3190,
        TANKS,
        (("burst", 0.85), ("ad", 0.55), ("ap", 0.55)),
        "armor",
        "A team shield with armor and magic resist",
    ),
    ItemRule(3109, TANKS, (("ad", 1.0), ("burst", 0.35)), "armor", "Armor that links to an ally"),
    ItemRule(3089, AP, (), "capstone", "Ability power for spells", 1.85, "core"),
    ItemRule(6655, frozenset({"Mage", "Battlemage"}), (("burst", 0.35),), "poke", "Ability power that procs on spells", 1.75, "core"),
    ItemRule(4645, AP, (), "core", "Ability power and magic penetration for spells", 1.6, "core"),
    ItemRule(4629, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power and ability haste for spells", 1.15, "core"),
    ItemRule(4646, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power burst for a mage", 1.5, "core"),
    ItemRule(4633, frozenset({"Battlemage"}), (), "core", "Ability power and health for a battlemage", 1.7, "core"),
    ItemRule(3031, frozenset({"Marksman", "Fighter"}), (), "crit", "Critical strike for auto attacks", 1.85, "core"),
    ItemRule(6676, frozenset({"Marksman"}), (), "core", "Critical strike and an execute for a marksman", 1.45, "core"),
    ItemRule(3094, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.35),), "zeal", "Attack speed for auto attacks", 1.6, "core"),
    ItemRule(3046, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.3),), "dancer", "A second attack-speed item for auto attacks", 1.45, "core"),
    ItemRule(3072, frozenset({"Marksman", "Fighter"}), (), "core", "Attack damage and lifesteal for auto attacks", 1.55, "core"),
    ItemRule(6672, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.25),), "core", "Attack damage and attack speed for auto attacks", 1.5, "core"),
    ItemRule(3142, frozenset({"Assassin"}), (), "core", "Lethality for an assassin's abilities", 1.7, "core"),
    ItemRule(6692, frozenset({"Assassin", "Fighter"}), (), "core", "Attack damage for short trades", 1.6, "core"),
    ItemRule(6698, frozenset({"Assassin"}), (), "core", "Lethality and ability haste for abilities", 1.55, "core"),
    ItemRule(3078, frozenset({"Fighter"}), (("attack_speed", 0.2),), "core", "Attack damage, attack speed, and ability haste for a fighter", 1.65, "core"),
    ItemRule(6631, frozenset({"Fighter"}), (), "core", "Attack damage and a slow for a fighter", 1.5, "core"),
    ItemRule(3161, frozenset({"Fighter", "Assassin", "Marksman"}), (), "core", "Ability haste and attack damage", 1.45, "core"),
    ItemRule(3004, frozenset({"Marksman"}), (), "core", "Attack damage and mana that grows from spells", 1.15, "core"),
    ItemRule(3508, frozenset({"Marksman", "Fighter"}), (), "core", "Critical strike and a spellblade", 1.2, "core"),
    ItemRule(3115, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power and attack speed on hit", 1.3),
    ItemRule(3100, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power and a spellblade", 1.2),
    ItemRule(3116, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power and a slow", 1.15),
    ItemRule(6657, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power and health that stacks", 1.2),
    ItemRule(3124, frozenset({"Marksman", "Fighter"}), (), "core", "Attack speed that converts critical strike", 1.25),
    ItemRule(3074, AD_BRUISER, (), "cleave", "Damage and healing for a fighter", 1.6, "core"),
    ItemRule(3083, frozenset({"Tank"}), (), "sustain", "Health for a tank", 1.2, "core"),
    ItemRule(6617, frozenset({"Support"}), (), "core", "Healing for an enchanter", 1.8, "core"),
    ItemRule(3107, frozenset({"Support"}), (), "core", "A team heal for an enchanter", 1.6, "core"),
    ItemRule(6616, frozenset({"Support"}), (), "core", "Ability power for an enchanter and an ally", 1.5, "core"),
    ItemRule(2065, frozenset({"Support"}), (), "core", "A movespeed active for an enchanter", 1.45, "core"),
    ItemRule(3504, frozenset({"Support"}), (), "core", "Attack speed for the ally an enchanter is shielding", 1.4, "core"),
    ItemRule(3222, frozenset({"Support"}), (), "core", "A cleanse for an enchanter", 1.35, "core"),
)


@dataclass(frozen=True)
class Recommendation:
    completed_id: int
    completed_name: str
    completed_total: int
    buy_id: int
    buy_name: str
    cost: int
    combine: bool
    affordable: bool
    gold_short: int
    why: str
    kind: str
    have: tuple[str, ...]
    sell_id: int = 0
    sell_name: str = ""
    sell_why: str = ""


@dataclass(frozen=True)
class SellChoice:
    item_id: int
    name: str
    why: str


def _pool(owned: dict[int, int]) -> Counter[int]:
    return Counter({item_id: count for item_id, count in owned.items() if count > 0})


def frontier_buys(completed_id: int, owned: dict[int, int], items: dict[int, Item]) -> list[int]:
    """Item ids you can buy or combine next toward completed_id."""
    pool = _pool(owned)
    found: list[int] = []

    def walk(item_id: int) -> bool:
        if pool[item_id] > 0:
            pool[item_id] -= 1
            return True
        meta = items.get(item_id)
        components = () if meta is None else meta.from_ids
        if meta is None or not components:
            found.append(item_id)
            return False
        ready = True
        for component in components:
            if not walk(component):
                ready = False
        if ready:
            found.append(item_id)
        return False

    if walk(completed_id):
        return []
    return found


def next_purchase(
    completed_id: int,
    owned: dict[int, int],
    gold: float,
    items: dict[int, Item],
) -> tuple[int, int, bool] | None:
    """Return (item id, gold to pay, is a combine) or None if it is already owned."""
    if owned.get(completed_id, 0) > 0:
        return None
    priced: list[tuple[int, int, bool]] = []
    for item_id in frontier_buys(completed_id, owned, items):
        meta = items.get(item_id)
        if meta is None:
            continue
        cost = meta.shop_price()
        priced.append((cost, item_id, bool(meta.from_ids)))
    if not priced:
        return None
    affordable = [row for row in priced if row[0] <= gold]
    pool = affordable or priced
    pool.sort()
    cost, item_id, combine = pool[0]
    return item_id, cost, combine


def _owned_names(completed_id: int, owned: dict[int, int], items: dict[int, Item]) -> tuple[str, ...]:
    pool = _pool(owned)
    names: list[str] = []

    def visit(item_id: int) -> None:
        if pool[item_id] > 0:
            pool[item_id] -= 1
            meta = items.get(item_id)
            if meta is not None and item_id != completed_id:
                names.append(meta.name)
            return
        meta = items.get(item_id)
        if meta is None:
            return
        for component in meta.from_ids:
            visit(component)

    visit(completed_id)
    compressed: list[str] = []
    counts = Counter(names)
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        count = counts[name]
        compressed.append(name if count == 1 else f"{name} x{count}")
    return tuple(compressed[:4])


def _owns_boots(owned: dict[int, int], items: dict[int, Item]) -> bool:
    """True once a finished pair is in the inventory.

    Basic Boots are the component. The next buy can still finish that pair.
    """
    for item_id, count in owned.items():
        if count <= 0 or item_id == BASIC_BOOTS_ID:
            continue
        meta = items.get(item_id)
        if meta is not None and "Boots" in meta.tags:
            return True
    return False


def component_ids(item_id: int, items: dict[int, Item]) -> set[int]:
    found: set[int] = set()
    stack = [item_id]
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        meta = items.get(current)
        if meta is None:
            continue
        stack.extend(meta.from_ids)
        if meta.special_recipe:
            stack.append(meta.special_recipe)
    return found


def unique_keys(item_id: int, items: dict[int, Item]) -> set[str]:
    """Shop locks that this item belongs to: boots, Lifeline, Last Whisper, and the rest."""
    meta = items.get(item_id)
    if meta is None:
        return set()
    keys = set(meta.uniques)
    if "Boots" in meta.tags:
        keys.add("boots")
    comps = component_ids(item_id, items)
    if LAST_WHISPER_ID in comps:
        keys.add("last_whisper")
    if TEAR_ID in comps:
        keys.add("tear")
    return keys


def completion_blocked(
    completed_id: int,
    owned: dict[int, int],
    items: dict[int, Item],
    ignore: set[int] | None = None,
) -> bool:
    """True when the completed item is owned or a one-of rule already used its component.

    A loose component of this same item does not block it. That component is
    progress, and the next buy is whatever piece is still missing. `ignore`
    skips a finished pair that this buy is replacing.
    """
    if owned.get(completed_id, 0) > 0:
        return True
    keys = unique_keys(completed_id, items)
    if not keys:
        return False
    parts = component_ids(completed_id, items)
    skipped = ignore or set()
    for owned_id, count in owned.items():
        if count <= 0 or owned_id in parts or owned_id in skipped:
            continue
        if unique_keys(owned_id, items) & keys:
            return True
    return False


# Attack-damage items that only an auto attacker should build.
_AUTO_DAMAGE = {3031, 3094, 3046, 3072, 6672, 6673, 3085}
# Finished items an enchanter can actually use. Damage legendaries are not on this list.
_ENCHANTER_ITEMS = {6617, 3222, 3107, 3504, 6616, 2065, 3190, 3157, 3102, 3165, 124011}
# Heal and shield power. Spell-damage tags on these do not make them a mage item.
_HEAL_POWER_ITEMS = {6617, 3222, 3107, 3504, 6616, 2065, 4005, 6620, 6621, 124011}


def _boots_fit(tags: set[str], kit: Kit) -> bool:
    sorcs = "MagicPenetration" in tags
    zerkers = "AttackSpeed" in tags
    defensive = "Armor" in tags or "SpellBlock" in tags
    ionian = "CooldownReduction" in tags
    if kit.damage == "tank":
        return defensive
    if kit.role == "Enchanter":
        return defensive or ionian
    if kit.damage == "ap":
        if kit.pattern == "auto":
            return sorcs or zerkers or defensive
        return sorcs or defensive or ionian
    if kit.pattern == "spell":
        return defensive or ionian
    if kit.pattern == "auto":
        return zerkers or defensive
    return zerkers or defensive or ionian


def item_fits_kit(meta: Item, kind: str, kit: Kit) -> bool:
    """True when this finished item belongs on this champion, not only on the enemy team."""
    tags = set(meta.tags)
    boots = "Boots" in tags or kind == "boots"
    if boots:
        return _boots_fit(tags, kit)
    if kit.role == "Enchanter":
        return meta.id in _ENCHANTER_ITEMS
    if meta.id in _HEAL_POWER_ITEMS:
        return False
    if meta.id == 3039 and kit.damage == "tank":
        return True
    ad_item = ("Damage" in tags or "CriticalStrike" in tags or "ArmorPenetration" in tags) and "SpellDamage" not in tags
    ap_item = "SpellDamage" in tags or ("MagicPenetration" in tags and not boots)
    if kit.damage == "tank":
        if kind in {"crit", "zeal", "dancer", "cleave", "capstone"}:
            return False
        if "CriticalStrike" in tags and "Health" not in tags:
            return False
        if ap_item and "Health" not in tags and "Armor" not in tags and "SpellBlock" not in tags:
            return False
        if ad_item and "Health" not in tags and "Armor" not in tags and "SpellBlock" not in tags:
            return False
        return True
    if meta.id in _AUTO_DAMAGE:
        return kit.damage == "ad" and (kit.role == "Marksman" or kit.pattern == "auto")
    if kit.damage == "ap":
        if ad_item or ("CriticalStrike" in tags and "SpellDamage" not in tags):
            return False
        if "AttackSpeed" in tags and "SpellDamage" not in tags:
            return False
        if not ap_item and tags & {"Armor", "SpellBlock", "Health"}:
            return False
        return True
    if ap_item and "Damage" not in tags:
        return False
    if kind == "capstone":
        return False
    if kit.role == "Marksman" and not ad_item and "AttackSpeed" not in tags and "ArmorPenetration" not in tags:
        if tags & {"Armor", "SpellBlock", "Health"}:
            return False
    return True


def _other_finished_boots(owned: dict[int, int], items: dict[int, Item], completed_id: int) -> set[int]:
    """Finished boots other than this pair. Basic Boots stay a component, not a swap."""
    parts = component_ids(completed_id, items)
    found: set[int] = set()
    for item_id, count in owned.items():
        if count <= 0 or item_id in {completed_id, BASIC_BOOTS_ID} or item_id in parts:
            continue
        meta = items.get(item_id)
        if meta is not None and "Boots" in meta.tags:
            found.add(item_id)
    return found


def _lookup_item(item_id: int, items: dict[int, Item]) -> Item | None:
    meta = items.get(item_id)
    if meta is None and item_id >= 10000:
        meta = items.get(item_id % 10000)
    return meta


def item_pressure(
    builds: tuple[tuple[str, tuple[int, ...]], ...] | list,
    items: dict[int, Item],
) -> tuple[dict[str, float], dict[str, list[str]], str]:
    """Extra threat from the items enemies already bought."""
    totals = {"heal": 0.0, "tank": 0.0, "mr": 0.0, "shield": 0.0}
    names: dict[str, list[str]] = {key: [] for key in totals}
    grouped = {"tank": [], "mr": [], "heal": [], "shield": []}
    for champ_name, ids in builds:
        heal = armor = resist = shield = 0.0
        for raw_id in ids:
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            meta = _lookup_item(item_id, items)
            if meta is None:
                continue
            tags = set(meta.tags)
            # Zhonya's and Wooglet's list Armor, but they are ability-power items.
            mage_item = "SpellDamage" in tags
            if tags & {"LifeSteal", "SpellVamp"} and meta.total >= 400:
                heal += 0.9 if meta.total >= 2000 else 0.55
            if "Armor" in tags and not mage_item and meta.total >= 300:
                armor += 0.45 if meta.total >= 1000 else 0.2
            if "SpellBlock" in tags and not mage_item and meta.total >= 300:
                resist += 0.45 if meta.total >= 1000 else 0.2
            if "Health" in tags and not mage_item and meta.total >= 2500:
                armor += 0.25
            if "lifeline" in meta.uniques or "shield" in meta.name.casefold():
                shield += 1.0
        if heal > 0:
            totals["heal"] += min(heal, 1.5)
            grouped["heal"].append(str(champ_name))
            names["heal"].append(str(champ_name))
        if armor > 0:
            totals["tank"] += min(armor, 1.2)
            grouped["tank"].append(str(champ_name))
            names["tank"].append(str(champ_name))
        if resist > 0:
            totals["mr"] += min(resist, 1.2)
            grouped["mr"].append(str(champ_name))
            names["mr"].append(str(champ_name))
        if shield > 0:
            totals["shield"] += shield
            grouped["shield"].append(str(champ_name))
            names["shield"].append(str(champ_name))
    parts: list[str] = []
    labels = (
        ("tank", "armor"),
        ("mr", "magic resist"),
        ("heal", "healing"),
        ("shield", "shields"),
    )
    for key, label in labels:
        found: list[str] = []
        for name in grouped[key]:
            if name not in found:
                found.append(name)
        if found:
            parts.append(f"{label} on " + ", ".join(found[:3]))
    line = "They're building: " + "; ".join(parts) + "." if parts else ""
    return totals, names, line


def absorb_pressure(threats: object, builds: tuple | list, items: dict[int, Item]) -> str:
    totals, names, line = item_pressure(builds, items)
    threats.heal += totals["heal"]  # type: ignore[attr-defined]
    threats.tank += totals["tank"]  # type: ignore[attr-defined]
    if hasattr(threats, "mr"):
        threats.mr += totals["mr"]  # type: ignore[attr-defined]
    if hasattr(threats, "shield"):
        threats.shield += totals["shield"]  # type: ignore[attr-defined]
    threat_names = getattr(threats, "names", None)
    if isinstance(threat_names, dict):
        for tag, found in names.items():
            bucket = threat_names.setdefault(tag, [])
            for name in found:
                if name not in bucket:
                    bucket.append(name)
    return line


def enemy_build_line(builds: tuple | list, items: dict[int, Item]) -> str:
    _totals, _names, line = item_pressure(builds, items)
    return line


def _grievous_allow(owned: dict[int, int]) -> set[int] | None:
    if any(owned.get(item_id, 0) > 0 for item_id in GRIEVOUS_IDS):
        return set()
    allow: set[int] | None = None
    for component_id, built in COMPONENT_LOCK.items():
        if owned.get(component_id, 0) <= 0:
            continue
        allow = set(built) if allow is None else allow & built
    return allow


def _shop_item(meta: Item | None) -> bool:
    if meta is None:
        return False
    if meta.id >= 10000:
        return False
    if not meta.purchasable or not meta.summoners_rift or not meta.in_store:
        return False
    if meta.required_champion:
        return False
    return True


def _explain(rule: ItemRule, threats: Threats) -> str:
    ranked: list[tuple[float, str, float]] = []
    for tag, weight in rule.weights:
        value = threats.value(tag)
        ranked.append((value * weight, tag, value))
    ranked.sort(reverse=True)
    bits: list[str] = []
    for score, tag, value in ranked:
        if value <= 0 or score <= 0:
            continue
        names = threats.names.get(tag) or []
        shown = ", ".join(names[:3])
        label = TAG_WORD.get(tag, tag)
        bits.append(f"{label} vs {shown}" if shown else label)
        if len(bits) == 2:
            break
    if not bits:
        return rule.summary
    return f"{rule.summary} - {'; '.join(bits)}"


def _who(threats: object, *tags: str) -> str:
    names = getattr(threats, "names", None) or {}
    found: list[str] = []
    for tag in tags:
        for name in names.get(tag) or []:
            text = str(name).strip()
            if text and text not in found:
                found.append(text)
    if not found:
        return ""
    if len(found) == 1:
        return found[0]
    if len(found) == 2:
        return f"{found[0]} and {found[1]}"
    return f"{found[0]}, {found[1]}, and {found[2]}"


def _from(names: str) -> str:
    return f" from {names}" if names else ""


def _against(names: str) -> str:
    return f" against {names}" if names else ""


def _direct_parents(items: dict[int, Item]) -> dict[int, tuple[int, ...]]:
    parents: dict[int, list[int]] = {}
    for meta in items.values():
        for component in meta.from_ids:
            parents.setdefault(int(component), []).append(meta.id)
        if meta.special_recipe:
            parents.setdefault(meta.special_recipe, []).append(meta.id)
    return {item_id: tuple(ids) for item_id, ids in parents.items()}


def _on_this_map(meta: Item, bridge: bool) -> bool:
    if not meta.purchasable or not meta.in_store or meta.required_champion:
        return False
    if bridge:
        return meta.howling_abyss
    return meta.summoners_rift


def _orphan_component(
    item_id: int,
    owned: dict[int, int],
    items: dict[int, Item],
    parents: dict[int, tuple[int, ...]],
    bridge: bool,
) -> bool:
    """True when this component no longer finishes a legal item on this map."""
    direct = parents.get(item_id) or ()
    if not direct:
        return False
    on_map: list[int] = []
    for parent_id in direct:
        meta = items.get(parent_id)
        if meta is not None and _on_this_map(meta, bridge):
            on_map.append(parent_id)
    if not on_map:
        return True
    rest = {key: value for key, value in owned.items() if key != item_id and value > 0}
    for parent_id in on_map:
        if not completion_blocked(parent_id, rest, items):
            return False
    return True


def _only_boots(owned: dict[int, int], items: dict[int, Item]) -> set[int]:
    found: list[int] = []
    for item_id, count in owned.items():
        if count <= 0:
            continue
        meta = items.get(item_id)
        if meta is not None and "Boots" in meta.tags:
            found.append(item_id)
    if len(found) == 1:
        return {found[0]}
    return set()


def _sell_role(meta: Item, heal: float) -> str:
    tags = set(meta.tags)
    if meta.id in GRIEVOUS_IDS and heal >= 1:
        return "grievous"
    if "Boots" in tags:
        return "boots"
    if "Armor" in tags and "SpellDamage" not in tags:
        return "armor"
    if "SpellBlock" in tags and "SpellDamage" not in tags:
        return "mr"
    if "MagicPenetration" in tags:
        return "magicpen"
    if "ArmorPenetration" in tags:
        return "armorpen"
    if "SpellDamage" in tags:
        return "spell"
    if "Damage" in tags or "CriticalStrike" in tags:
        return "attack"
    return "other"


def _keep_score(
    meta: Item,
    threats: object,
    *,
    count: int,
    profile: str,
    bridge: bool,
    orphan: bool,
    mr_built: str,
    kit: Kit | None = None,
) -> tuple[float, str, bool]:
    """Higher score means the item still matches the game and should stay."""
    if orphan:
        place = "on this bridge" if bridge else "in this game"
        return -8.0, f"It no longer builds into an item you can finish {place}", True
    tags = set(meta.tags)
    ad = threats.value("ad") + 0.5 * threats.value("attack_speed")  # type: ignore[attr-defined]
    ap = threats.value("ap")  # type: ignore[attr-defined]
    heal = threats.value("heal")  # type: ignore[attr-defined]
    tank = threats.value("tank")  # type: ignore[attr-defined]
    magic_names = _who(threats, "ap")
    physical_names = _who(threats, "ad", "attack_speed")
    heal_names = _who(threats, "heal")
    enemy = _who(threats, "ap", "ad", "heal", "tank")
    score = 0.0
    penalties: list[tuple[float, str]] = []
    boots = "Boots" in tags
    grievous_matters = meta.id in GRIEVOUS_IDS and heal >= 1
    if "Armor" in tags and "SpellDamage" not in tags and not boots and not grievous_matters:
        if ap >= ad + 0.75:
            why = f"Their damage is magic{_from(magic_names)}"
            if mr_built:
                why += f", and {mr_built} stacked magic resist"
            penalties.append((3.0, why))
        else:
            score += ad * 2.2
    if "SpellBlock" in tags and "SpellDamage" not in tags and not boots:
        if ad >= ap + 0.75 and ap < 1.25:
            penalties.append((3.0, f"Their damage is physical{_from(physical_names)}"))
        else:
            score += ap * 2.2
    if meta.id in GRIEVOUS_IDS:
        if heal >= 1:
            score += heal * 2.6
            if "Armor" in tags and "SpellDamage" not in tags:
                score += ad * 2.2
        else:
            penalties.append((1.5, f"Healing is not the threat{_from(heal_names)}"))
    if "ArmorPenetration" in tags and tank < 0.8:
        penalties.append((1.2, "They are not stacking armor"))
    elif "ArmorPenetration" in tags:
        score += tank * 1.3
    if "MagicPenetration" in tags and threats.value("mr") < 0.5:  # type: ignore[attr-defined]
        penalties.append((0.6, "Nobody has stacked magic resist"))
    elif "MagicPenetration" in tags:
        score += threats.value("mr") * 1.1  # type: ignore[attr-defined]
    if "SpellDamage" in tags:
        score += 1.4
        if "Health" in tags:
            score += tank * 0.7
    if ("Damage" in tags or "CriticalStrike" in tags) and "SpellDamage" not in tags:
        if profile in {"Mage", "Battlemage", "Support"}:
            penalties.append((2.2, f"It is attack damage in a magic build{_against(enemy)}"))
        else:
            score += 1.3
    if (
        "SpellDamage" in tags
        and "Damage" not in tags
        and "Armor" not in tags
        and "SpellBlock" not in tags
        and profile in {"Marksman", "Fighter", "Assassin"}
    ):
        penalties.append((2.0, f"It is ability power in an attack-damage build{_against(enemy)}"))
    if count > 1:
        penalties.append((0.75, "A second copy adds less than the rest of this inventory"))
    score -= sum(amount for amount, _why in penalties)
    shopper = kit or _kit_from_profile(profile)
    if not item_fits_kit(meta, "answer", shopper):
        # A wrong-stat item does not keep its resist score. The specific reason stays.
        score = min(score, 0.0) - 3.0
        if not penalties:
            penalties.append((3.0, "It does not fit this champion"))
    if not penalties:
        return score, "", False
    penalties.sort(key=lambda row: row[0], reverse=True)
    return score, penalties[0][1], True


def _kit_from_profile(profile: str) -> Kit:
    if profile == "Tank":
        return Kit(profile, "tank", "both", "Tank")
    if profile == "Support":
        return Kit(profile, "ap", "spell", "Enchanter")
    if profile == "Mage":
        return Kit(profile, "ap", "spell", "Mage")
    if profile == "Battlemage":
        return Kit(profile, "ap", "both", "Battlemage")
    if profile == "Marksman":
        return Kit(profile, "ad", "auto", "Marksman")
    if profile == "Assassin":
        return Kit(profile, "ad", "spell", "Assassin")
    return Kit(profile, "ad", "both", profile)


def choose_sell(
    owned: dict[int, int],
    items: dict[int, Item],
    threats: object,
    *,
    protected_ids: set[int],
    locked_ids: set[int],
    profile: str,
    enemy_builds: tuple | list = (),
    bridge: bool = False,
    inventory_full: bool = False,
    item_labels: dict[int, str] | None = None,
    kit: Kit | None = None,
    allow_boot_sell: bool = False,
) -> SellChoice | None:
    """Owned item that least matches this game, or None when a slot is open.

    Never returns the only boots, the buy being recommended, a one-off
    component of that buy, or an item that is not in the inventory.
    """
    if not inventory_full:
        return None
    labels = item_labels or {}
    locked = set(locked_ids)
    if not allow_boot_sell:
        locked |= _only_boots(owned, items)
    parents = _direct_parents(items)
    _totals, built, _line = item_pressure(enemy_builds, items)
    mr_built = _who_list(built.get("mr") or [])
    enemy = _who(threats, "ap", "ad", "heal", "tank")
    heal = threats.value("heal")  # type: ignore[attr-defined]
    rows: list[tuple[float, int, int, str, str, bool, str]] = []
    for item_id, count in owned.items():
        if count <= 0 or item_id in locked:
            continue
        if item_id in protected_ids and count <= 1:
            continue
        meta = items.get(item_id)
        if meta is None:
            continue
        orphan = _orphan_component(item_id, owned, items, parents, bridge)
        score, why, specific = _keep_score(
            meta,
            threats,
            count=count,
            profile=profile,
            bridge=bridge,
            orphan=orphan,
            mr_built=mr_built,
            kit=kit,
        )
        label = labels.get(item_id) or meta.name
        rows.append((score, meta.total, item_id, label, why, specific, _sell_role(meta, heal)))
    if not rows:
        return None
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    score, _total, item_id, label, why, specific, role = rows[0]
    if owned.get(item_id, 0) <= 0:
        return None
    if not specific:
        peers = [
            row
            for row in rows[1:]
            if row[6] == role and row[2] != item_id and (row[0] > score or (row[0] == score and row[1] > _total))
        ]
        peers.sort(key=lambda row: (-row[0], -row[1]))
        if peers and role == "spell" and peers[0][0] > score + 0.05:
            why = f"{peers[0][3]} already covers magic damage{_against(enemy)}"
        elif peers:
            why = f"{peers[0][3]} already covers this job{_against(enemy)}"
        else:
            why = f"It adds the least{_against(enemy)}"
    return SellChoice(item_id, label, why)


def _who_list(names: list[str]) -> str:
    found: list[str] = []
    for name in names:
        text = str(name).strip()
        if text and text not in found:
            found.append(text)
    if not found:
        return ""
    if len(found) == 1:
        return found[0]
    if len(found) == 2:
        return f"{found[0]} and {found[1]}"
    return f"{found[0]}, {found[1]}, and {found[2]}"


def sell_for_buy(
    owned: dict[int, int],
    items: dict[int, Item],
    threats: object,
    completed_id: int,
    buy_id: int,
    profile: str,
    enemy_builds: tuple | list,
    *,
    bridge: bool,
    inventory_full: bool,
    item_labels: dict[int, str] | None = None,
    keep_ids: set[int] | None = None,
    kit: Kit | None = None,
) -> SellChoice | None:
    if not inventory_full:
        return None
    parts = component_ids(completed_id, items)
    progress = {
        item_id
        for item_id, count in owned.items()
        if count > 0 and item_id in parts and item_id != completed_id
    }
    locked = {completed_id, buy_id}
    if keep_ids:
        locked |= set(keep_ids)
    completed = items.get(completed_id)
    shopper = kit or _kit_from_profile(profile)
    if completed is not None and not item_fits_kit(completed, "answer", shopper):
        for item_id, count in owned.items():
            owned_meta = items.get(item_id)
            if count > 0 and owned_meta is not None and item_fits_kit(owned_meta, "answer", shopper):
                locked.add(item_id)
    swapping_boots = completed is not None and "Boots" in completed.tags
    return choose_sell(
        owned,
        items,
        threats,
        protected_ids=progress,
        locked_ids=locked,
        profile=profile,
        enemy_builds=enemy_builds,
        bridge=bridge,
        inventory_full=True,
        item_labels=item_labels,
        kit=shopper,
        allow_boot_sell=swapping_boots,
    )


def _with_sell(rec: Recommendation, sell: SellChoice | None) -> Recommendation:
    if sell is None:
        return rec
    return replace(rec, sell_id=sell.item_id, sell_name=sell.name, sell_why=sell.why)


@dataclass(frozen=True)
class ScoredBuy:
    score: float
    item_id: int
    kind: str
    name: str
    rule: object


@dataclass(frozen=True)
class BootsSell:
    """One finished item bought by selling the boots he already owns."""

    item_name: str
    boot_name: str
    boot_id: int
    ready: bool
    buy: Recommendation | None = None


@dataclass(frozen=True)
class ShopAdvice:
    buys: tuple[Recommendation, ...]
    plan: tuple[str, ...]
    complete: bool
    focus: str = ""
    boots_sell: BootsSell | None = None


def boots_sell_line(option: BootsSell | None) -> str:
    """The panel line for the boots swap. Empty until he owns a finished pair."""
    if option is None:
        return ""
    when = "now" if option.ready else "later"
    return f"Boots-sell {when}: {option.item_name}. Sell {option.boot_name}."


def _row_is_boots(row: ScoredBuy, items: dict[int, Item]) -> bool:
    if row.kind == "boots":
        return True
    meta = items.get(row.item_id)
    return meta is not None and "Boots" in meta.tags


def choose_boots_sell(
    scored: list[ScoredBuy],
    plan: list[ScoredBuy],
    owned: dict[int, int],
    gold: float,
    items: dict[int, Item],
    *,
    inventory_full: bool,
    explain,
    kit: Kit | None,
) -> BootsSell | None:
    """The late item his boots can become, shown as soon as the pair is owned.

    The next buy stays on the six-slot plan until that plan's other items are
    finished. Full build and high gold are that same moment: the five are in
    the inventory and the gold is sitting there.
    """
    boot_id = _finished_boots_id(owned, items)
    boot = items.get(boot_id) if boot_id else None
    if boot is None:
        return None
    plan_ids = {row.item_id for row in plan}
    best: ScoredBuy | None = None
    for row in scored:
        if _row_is_boots(row, items) or row.item_id in plan_ids:
            continue
        if owned.get(row.item_id, 0) > 0 or row.kind == "starter":
            continue
        if getattr(row.rule, "early_only", False):
            continue
        if completion_blocked(row.item_id, owned, items):
            continue
        if best is None or (row.score, -row.item_id) > (best.score, -best.item_id):
            best = row
    if best is None:
        return None
    non_boots = [row for row in plan if not _row_is_boots(row, items)]
    five_done = bool(non_boots) and all(owned.get(row.item_id, 0) > 0 for row in non_boots)
    full_build = inventory_full and five_done
    high_gold = gold >= HIGH_BOOT_GOLD and five_done
    ready = five_done or full_build or high_gold
    buy: Recommendation | None = None
    if ready:
        step = next_purchase(best.item_id, owned, gold, items)
        buy_meta = items.get(step[0]) if step is not None else None
        completed = items.get(best.item_id)
        if step is None or buy_meta is None or completed is None:
            return None
        buy_id, cost, combine = step
        why = explain(best.rule) if best.rule is not None else completed.name
        if kit is not None:
            why = f"{why.rstrip('.')}. Fits {kit_focus(kit)}."
        why = f"Boots-sell option. {why}"
        if full_build and high_gold:
            sell_why = "Full build and high gold. The other five planned items are finished."
        elif full_build:
            sell_why = "Full build. The other five planned items are finished."
        elif high_gold:
            sell_why = "High gold. The other five planned items are finished."
        else:
            sell_why = "The other five planned items are finished."
        short = 0 if gold >= cost else max(1, math.ceil(cost - gold))
        buy = _with_sell(
            Recommendation(
                completed_id=completed.id,
                completed_name=completed.name,
                completed_total=completed.total,
                buy_id=buy_meta.id,
                buy_name=buy_meta.name,
                cost=cost,
                combine=combine,
                affordable=gold >= cost,
                gold_short=short,
                why=why,
                kind=best.kind,
                have=_owned_names(completed.id, owned, items),
            ),
            SellChoice(boot.id, boot.name, sell_why),
        )
    return BootsSell(best.name, boot.name, boot.id, ready, buy)


def _apply_boots_sell(
    buys: list[Recommendation],
    option: BootsSell | None,
    limit: int,
) -> list[Recommendation]:
    if option is None or option.buy is None:
        return buys
    return [option.buy, *buys][:limit]


def _finished_boots_id(owned: dict[int, int], items: dict[int, Item]) -> int:
    for item_id, count in owned.items():
        if count <= 0 or item_id == BASIC_BOOTS_ID:
            continue
        meta = items.get(item_id)
        if meta is not None and "Boots" in meta.tags:
            return item_id
    return 0


def _conflicts(item_id: int, chosen_ids: list[int], items: dict[int, Item]) -> bool:
    keys = unique_keys(item_id, items)
    if not keys:
        return False
    parts = component_ids(item_id, items)
    for other in chosen_ids:
        if other == item_id or other in parts:
            continue
        if unique_keys(other, items) & keys:
            return True
    return False


def _in_progress(item_id: int, owned: dict[int, int], items: dict[int, Item]) -> bool:
    if owned.get(item_id, 0) > 0:
        return False
    parts = component_ids(item_id, items)
    return any(owned.get(part, 0) > 0 and part != item_id for part in parts)


def tune_rule(rule, kit: Kit):
    """Promote a kit's own item into a core slot, and scale the score."""
    mult = dict(kit.item_mult).get(rule.item_id, 1.0)
    bonus = 1.5 if rule.item_id in kit.cores else 0.0
    if rule.item_id in kit.cores:
        rule = replace(rule, job="core")
    return rule, mult, bonus


def _is_core(row: ScoredBuy) -> bool:
    return getattr(row.rule, "job", "answer") == "core"


def _stacked_resist(row: ScoredBuy, chosen: list[ScoredBuy], items: dict[int, Item]) -> bool:
    """A second attack-damage magic-resist item crowds out the damage his kit scales with."""
    if _is_core(row):
        return False
    meta = items.get(row.item_id)
    if meta is None or "Boots" in meta.tags:
        return False
    if "SpellBlock" not in meta.tags or "Damage" not in meta.tags:
        return False
    for other in chosen:
        if _is_core(other):
            continue
        other_meta = items.get(other.item_id)
        if other_meta is None or "Boots" in other_meta.tags:
            continue
        if "SpellBlock" in other_meta.tags and "Damage" in other_meta.tags:
            return True
    return False


def _legal_boots(scored: list[ScoredBuy], owned: dict[int, int], items: dict[int, Item]) -> list[ScoredBuy]:
    rows: list[ScoredBuy] = []
    for row in scored:
        if row.kind != "boots" or row.score <= 0:
            continue
        ignore = _other_finished_boots(owned, items, row.item_id)
        if completion_blocked(row.item_id, owned, items, ignore):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (-row.score, row.item_id))
    return rows


def select_plan(
    scored: list[ScoredBuy],
    owned: dict[int, int],
    items: dict[int, Item],
    core_slots: int = CORE_SLOTS,
) -> list[ScoredBuy]:
    """Up to six finished items for one champion: own build, then the enemy answers."""
    chosen: list[ScoredBuy] = []
    chosen_ids: list[int] = []

    def add(row: ScoredBuy) -> None:
        if row.item_id in chosen_ids:
            return
        chosen.append(row)
        chosen_ids.append(row.item_id)

    legal = _legal_boots(scored, owned, items)
    owned_boots = _finished_boots_id(owned, items)
    owned_row = next((row for row in legal if row.item_id == owned_boots), None)
    if owned_row is not None:
        add(owned_row)
    elif legal:
        add(legal[0])
    elif owned_boots:
        meta = items.get(owned_boots)
        add(ScoredBuy(0.0, owned_boots, "boots", meta.name if meta is not None else "Boots", None))

    def usable(row: ScoredBuy, same_kind: bool) -> bool:
        if row.item_id in chosen_ids or row.kind == "boots":
            return False
        if row.score < PLAN_FLOOR:
            return False
        if owned.get(row.item_id, 0) <= 0 and completion_blocked(row.item_id, owned, items):
            return False
        if _conflicts(row.item_id, chosen_ids, items):
            return False
        if not same_kind and any(other.kind == row.kind for other in chosen):
            return False
        if _stacked_resist(row, chosen, items):
            return False
        return True

    ordered = sorted(scored, key=lambda row: (-row.score, row.item_id))

    def owned_first(rows: list[ScoredBuy]) -> list[ScoredBuy]:
        have = [row for row in rows if owned.get(row.item_id, 0) > 0]
        missing = [row for row in rows if owned.get(row.item_id, 0) <= 0]
        return have + missing

    cores = owned_first([row for row in ordered if _is_core(row)])
    answers = owned_first([row for row in ordered if not _is_core(row) and row.kind != "boots"])

    def take(rows: list[ScoredBuy], limit: int) -> None:
        if limit <= 0:
            return
        start = len(chosen)
        for same_kind in (False, True):
            for row in rows:
                if len(chosen) - start >= limit or len(chosen) >= PLAN_SLOTS:
                    return
                if usable(row, same_kind):
                    add(row)

    legal_cores = 0
    for row in cores:
        if row.score < PLAN_FLOOR:
            continue
        if owned.get(row.item_id, 0) <= 0 and completion_blocked(row.item_id, owned, items):
            continue
        legal_cores += 1
    reserve = min(core_slots, legal_cores)
    take(answers, PLAN_SLOTS - len(chosen) - reserve)
    take(cores, PLAN_SLOTS - len(chosen))
    take(answers, PLAN_SLOTS - len(chosen))
    return chosen


def _order_buys(
    unfinished: list[ScoredBuy],
    owned: dict[int, int],
    items: dict[int, Item],
    limit: int,
) -> list[ScoredBuy]:
    """Highest counters first, one job at a time, then a repeat job if a slot is still open."""
    started = [row for row in unfinished if _in_progress(row.item_id, owned, items)]
    started.sort(key=lambda row: (-row.score, row.item_id))
    waiting = [row for row in unfinished if row.item_id not in {item.item_id for item in started}]
    cores = [row for row in waiting if _is_core(row)]
    rest = [row for row in waiting if not _is_core(row)]
    cores.sort(key=lambda row: (-row.score, row.item_id))
    rest.sort(key=lambda row: (-row.score, row.item_id))
    waiting = cores + rest
    picked: list[ScoredBuy] = list(started)
    seen = {row.kind for row in picked}
    deferred: list[ScoredBuy] = []
    for row in waiting:
        if len(picked) >= limit:
            break
        if row.kind in seen:
            deferred.append(row)
            continue
        seen.add(row.kind)
        picked.append(row)
    for row in deferred:
        if len(picked) >= limit:
            break
        picked.append(row)
    # A pair that does not fit this champion is replaced before a new component.
    fixing = [
        row
        for row in picked
        if row.kind == "boots" and _other_finished_boots(owned, items, row.item_id)
    ]
    if fixing:
        rest = [row for row in picked if row.item_id not in {item.item_id for item in fixing}]
        picked = fixing + rest
    return picked[:limit]


def buys_for_plan(
    plan: list[ScoredBuy],
    owned: dict[int, int],
    gold: float,
    items: dict[int, Item],
    threats: object,
    profile: str,
    enemy_builds: tuple | list,
    *,
    bridge: bool,
    inventory_full: bool,
    item_labels: dict[int, str] | None,
    limit: int,
    explain,
    kit: Kit | None = None,
) -> list[Recommendation]:
    unfinished = []
    for row in plan:
        if row.rule is None or owned.get(row.item_id, 0) > 0:
            continue
        ignore = _other_finished_boots(owned, items, row.item_id) if row.kind == "boots" else None
        if completion_blocked(row.item_id, owned, items, ignore):
            continue
        unfinished.append(row)
    picks: list[Recommendation] = []
    keep = {row.item_id for row in plan}
    for row in _order_buys(unfinished, owned, items, limit):
        step = next_purchase(row.item_id, owned, gold, items)
        if step is None:
            continue
        buy_id, cost, combine = step
        buy = items.get(buy_id)
        completed = items.get(row.item_id)
        if buy is None or completed is None:
            continue
        short = 0 if gold >= cost else max(1, math.ceil(cost - gold))
        why = explain(row.rule)
        if kit is not None:
            why = f"{why.rstrip('.')}. Fits {kit_focus(kit)}."
        started = _in_progress(row.item_id, owned, items)
        if not picks and started:
            why = f"Finish {completed.name}. {why}".strip()
        elif not picks and not inventory_full:
            why = f"Open slot: {completed.name}. {why}".strip()
        rec = Recommendation(
            completed_id=completed.id,
            completed_name=completed.name,
            completed_total=completed.total,
            buy_id=buy.id,
            buy_name=buy.name,
            cost=cost,
            combine=combine,
            affordable=gold >= cost,
            gold_short=short,
            why=why,
            kind=row.kind,
            have=_owned_names(completed.id, owned, items),
        )
        if inventory_full and not picks:
            rec = _with_sell(
                rec,
                sell_for_buy(
                    owned,
                    items,
                    threats,
                    completed.id,
                    buy.id,
                    profile,
                    enemy_builds,
                    bridge=bridge,
                    inventory_full=True,
                    item_labels=item_labels,
                    keep_ids=keep,
                    kit=kit,
                ),
            )
        picks.append(rec)
    return picks


def advise(
    champion: Champion,
    enemies: list[Champion],
    owned: dict[int, int],
    gold: float,
    items: dict[int, Item],
    enemy_builds: tuple[tuple[str, tuple[int, ...]], ...] | list = (),
    limit: int = 2,
    inventory_full: bool = False,
    item_labels: dict[int, str] | None = None,
) -> ShopAdvice:
    """The six-item plan, and the next buys that finish it."""
    threats = summarize(enemies)
    absorb_pressure(threats, enemy_builds, items)
    kit = champion_kit(champion)
    profile = kit.profile
    grievous_allow = _grievous_allow(owned)
    owned_boots = _finished_boots_id(owned, items)
    owned_boot = items.get(owned_boots) if owned_boots else None
    boots_fit = owned_boot is not None and item_fits_kit(owned_boot, "boots", kit)
    scored: list[ScoredBuy] = []
    for rule in RULES:
        if profile not in rule.profiles:
            continue
        if rule.kind == "boots" and not kit.boots:
            continue
        owned_this = owned.get(rule.item_id, 0) > 0
        if rule.kind == "boots" and boots_fit and rule.item_id != owned_boots:
            continue
        if rule.kind == "grievous" and grievous_allow is not None and rule.item_id not in grievous_allow and not owned_this:
            continue
        meta = items.get(rule.item_id)
        if not _shop_item(meta) or meta is None:
            continue
        if not item_fits_kit(meta, rule.kind, kit):
            continue
        ignore = _other_finished_boots(owned, items, rule.item_id) if rule.kind == "boots" else None
        if not owned_this and completion_blocked(rule.item_id, owned, items, ignore):
            continue
        rule, mult, bonus = tune_rule(rule, kit)
        score = rule.base + bonus + sum(threats.value(tag) * weight for tag, weight in rule.weights)
        score *= champion_factor(kit, set(meta.tags)) * mult
        if rule.item_id == 3065 and champion.id in HEAL_CHAMPS and threats.ap >= 1:
            score += 1.8
        floor = 0.0 if rule.kind == "boots" else PLAN_FLOOR
        if score < floor:
            continue
        scored.append(ScoredBuy(score, rule.item_id, rule.kind, meta.name, rule))
    plan = select_plan(scored, owned, items)
    buys = buys_for_plan(
        plan,
        owned,
        gold,
        items,
        threats,
        profile,
        enemy_builds,
        bridge=False,
        inventory_full=inventory_full,
        item_labels=item_labels,
        limit=limit,
        explain=lambda rule: _explain(rule, threats),
        kit=kit,
    )
    option = choose_boots_sell(
        scored,
        plan,
        owned,
        gold,
        items,
        inventory_full=inventory_full,
        explain=lambda rule: _explain(rule, threats),
        kit=kit,
    )
    buys = _apply_boots_sell(buys, option, limit)
    complete = bool(plan) and all(owned.get(row.item_id, 0) > 0 for row in plan)
    return ShopAdvice(tuple(buys), tuple(row.name for row in plan), complete, kit_focus(kit), option)


def recommend(
    champion: Champion,
    enemies: list[Champion],
    owned: dict[int, int],
    gold: float,
    items: dict[int, Item],
    enemy_builds: tuple[tuple[str, tuple[int, ...]], ...] | list = (),
    limit: int = 2,
    inventory_full: bool = False,
    item_labels: dict[int, str] | None = None,
) -> list[Recommendation]:
    """Up to `limit` buy paths, best counter first."""
    return list(
        advise(
            champion,
            enemies,
            owned,
            gold,
            items,
            enemy_builds,
            limit,
            inventory_full,
            item_labels,
        ).buys
    )
