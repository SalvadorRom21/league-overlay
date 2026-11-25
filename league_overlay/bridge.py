"""Shop and champion-select advice for ARAM and ARAM: Mayhem.

This is not the Summoner's Rift scorer. ARAM is one bridge: you buy in the
fountain, usually while dead, gold arrives faster, and health relics plus
poke decide fights. Mayhem keeps those rules and adds augments at levels 3,
7, 11, and 15, chosen when the fountain shop is open. Riot's mode notes and
the League wiki are the source for those rules. There are no win rates here.
"""

from __future__ import annotations

from dataclasses import dataclass

from league_overlay.augments import flags_from_text
from league_overlay.catalog import DragonData
from league_overlay.items import (
    PLAN_FLOOR,
    Recommendation,
    ScoredBuy,
    _grievous_allow,
    absorb_pressure,
    _finished_boots_id,
    _other_finished_boots,
    buys_for_plan,
    completion_blocked,
    item_fits_kit,
    select_plan,
)
from league_overlay.model import Champion, Item
from league_overlay.threats import (
    ENCHANTERS,
    HEAL_CHAMPS,
    build_profile,
    champion_kit,
    champion_factor,
    damage_type,
    damage_weight,
    kit_focus,
    tank_value,
)

# A bridge champion below this, with enemies already showing and rerolls left,
# is a weak lock. The bench is preferred when it scores higher.
REROLL_BELOW = 6.5
BOOTS_FACTOR = 0.3

# Artillery that Data Dragon does not already mark as a marksman or a squishy mage.
POKE_EXTRA = frozenset({"Jayce", "Kennen", "Zoe"})

# Mayhem shop legendaries. The 12xxxx ids are the Howling Abyss copies; the
# base ids are not flagged for that map in Data Dragon. Quest rewards
# (Golden Spatula, Wooglet's, and the rest) are not shop buys.
MAYHEM_LEGENDARIES = frozenset({3039, 123430, 124011})


@dataclass
class BridgeThreats:
    ad: float = 0.0
    ap: float = 0.0
    tank: float = 0.0
    heal: float = 0.0
    attack_speed: float = 0.0
    burst: float = 0.0
    poke: float = 0.0
    mr: float = 0.0
    shield: float = 0.0
    names: dict[str, list[str]] | None = None

    def __post_init__(self) -> None:
        if self.names is None:
            self.names = {
                key: []
                for key in ("ad", "ap", "tank", "heal", "attack_speed", "burst", "poke", "mr", "shield")
            }

    def value(self, tag: str) -> float:
        return float(getattr(self, tag, 0.0))


@dataclass(frozen=True)
class BridgeRule:
    item_id: int
    profiles: frozenset[str]
    weights: tuple[tuple[str, float], ...]
    kind: str
    summary: str
    base: float = 0.0
    mayhem_only: bool = False
    early_only: bool = False
    job: str = "answer"


ALL = frozenset({"Tank", "Fighter", "Assassin", "Marksman", "Mage", "Battlemage", "Support"})
AP = frozenset({"Mage", "Battlemage", "Support"})
FRONT = frozenset({"Tank", "Fighter", "Support"})
AD_BRUISER = frozenset({"Fighter", "Assassin"})
CARRY = frozenset({"Marksman", "Assassin", "Fighter"})

RULES: tuple[BridgeRule, ...] = (
    BridgeRule(2051, frozenset({"Tank", "Support"}), (), "starter", "A tank start for the first fountain", early_only=True, base=3.2),
    BridgeRule(3112, frozenset({"Mage", "Battlemage"}), (), "starter", "A mage start for the first fountain", early_only=True, base=3.2),
    BridgeRule(3184, frozenset({"Marksman", "Fighter", "Assassin"}), (), "starter", "An attacker start for the first fountain", early_only=True, base=3.2),
    BridgeRule(3047, ALL, (("ad", 1.2), ("attack_speed", 0.8)), "boots", "Armor boots, after a combat item", base=0.15),
    BridgeRule(3111, ALL, (("ap", 1.2), ("burst", 0.4)), "boots", "Magic-resist boots, after a combat item", base=0.15),
    BridgeRule(3020, AP, (), "boots", "Magic penetration boots for spells", base=1.6),
    BridgeRule(3006, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.2),), "boots", "Attack speed boots for auto attacks", base=1.6),
    BridgeRule(3158, frozenset({"Assassin", "Support"}), (), "boots", "Ability haste boots for spells", base=1.5),
    BridgeRule(
        3075,
        frozenset({"Tank", "Fighter", "Support"}),
        (("heal", 3.2), ("poke", 0.55), ("ad", 0.35)),
        "grievous",
        "Armor and grievous wounds. Relics and poke healing stretch a bridge fight",
    ),
    BridgeRule(
        3033,
        frozenset({"Marksman"}),
        (("heal", 3.2), ("poke", 0.45)),
        "grievous",
        "Grievous wounds and armor penetration for a marksman",
    ),
    BridgeRule(
        6609,
        AD_BRUISER,
        (("heal", 3.2), ("poke", 0.4)),
        "grievous",
        "Attack damage and grievous wounds",
    ),
    BridgeRule(
        3165,
        AP,
        (("heal", 3.2), ("poke", 0.5)),
        "grievous",
        "Ability power and grievous wounds for poke",
    ),
    BridgeRule(3083, frozenset({"Tank"}), (("poke", 1.15),), "sustain", "Health regen between waves. You do not recall to a side shop", base=2.0, job="core"),
    BridgeRule(3065, frozenset({"Tank", "Fighter", "Battlemage", "Support"}), (("ap", 0.8), ("poke", 0.35)), "sustain", "Magic resist that boosts your own healing", base=0.4),
    BridgeRule(4401, frozenset({"Tank", "Fighter", "Battlemage"}), (("ap", 1.35), ("poke", 0.45)), "mr", "Magic resist that stacks while spells keep landing"),
    BridgeRule(2504, frozenset({"Tank", "Support"}), (("ap", 1.05), ("poke", 0.7)), "mr", "A magic shield against repeated spells"),
    BridgeRule(3102, AP, (("poke", 1.15), ("burst", 0.7)), "mr", "A spell shield for standing in poke"),
    BridgeRule(3156, CARRY, (("ap", 1.1), ("poke", 0.4)), "mr", "A magic shield on an attack-damage item"),
    BridgeRule(3143, FRONT, (("ad", 0.85), ("attack_speed", 0.7)), "armor", "Armor against basic attacks on one lane"),
    BridgeRule(3110, frozenset({"Tank", "Support"}), (("attack_speed", 1.2), ("ad", 0.4)), "armor", "Armor and an attack-speed aura"),
    BridgeRule(3068, frozenset({"Tank"}), (("ad", 0.7),), "armor", "Armor that burns whoever stands on you", base=1.15, job="core"),
    BridgeRule(6664, frozenset({"Tank"}), (("ap", 0.35),), "mr", "Magic resist and a burn for a tank", base=1.15, job="core"),
    BridgeRule(3190, frozenset({"Tank", "Support"}), (("poke", 0.7), ("burst", 0.45)), "armor", "A team shield while everyone is in one fight"),
    BridgeRule(4628, AP, (("poke", 1.35),), "poke", "Damage on the long-range spells that define the bridge"),
    BridgeRule(6653, AP, (("tank", 1.45), ("poke", 0.35), ("mr", 1.15)), "poke", "A burn into the frontline you cannot walk around"),
    BridgeRule(6655, frozenset({"Mage", "Battlemage"}), (("burst", 0.8),), "poke", "Ability power that procs on spells", base=1.7, job="core"),
    BridgeRule(6695, CARRY, (("poke", 0.2),), "shields", "Cuts shields from an enemy item or augment", base=0.0),
    BridgeRule(3157, frozenset({"Mage", "Battlemage", "Support"}), (("burst", 1.25), ("ad", 0.55)), "anti_burst", "Stasis when the bridge fight collapses onto you"),
    BridgeRule(
        6673,
        frozenset({"Marksman"}),
        (("burst", 1.05), ("ad", 0.65), ("attack_speed", 0.55)),
        "anti_burst",
        "A shield against the all-in after poke",
    ),
    BridgeRule(
        3036,
        frozenset({"Marksman"}),
        (("tank", 2.0),),
        "pen",
        "Armor penetration into the frontline you cannot walk around",
    ),
    BridgeRule(
        3153,
        frozenset({"Marksman", "Fighter", "Assassin"}),
        (("tank", 1.5),),
        "pen",
        "Percent-health damage into the frontline",
    ),
    BridgeRule(3071, AD_BRUISER, (("tank", 1.65),), "pen", "Armor shred for physical damage on one lane"),
    BridgeRule(
        3139,
        frozenset({"Marksman", "Assassin"}),
        (("ap", 0.95), ("poke", 0.3)),
        "cleanse",
        "A cleanse when spells keep landing",
    ),
    BridgeRule(
        3814,
        frozenset({"Assassin"}),
        (("ap", 1.0), ("poke", 0.45)),
        "spellshield",
        "A spell shield so poke does not cancel the all-in",
    ),
    BridgeRule(3039, frozenset({"Tank", "Fighter"}), (("ad", 0.25),), "mayhem", "Mayhem item. Critical strike that scales with bonus health", base=0.85, mayhem_only=True),
    BridgeRule(
        123430,
        frozenset({"Mage", "Battlemage"}),
        (("poke", 0.35), ("burst", 0.2), ("mr", 0.8)),
        "mayhem",
        "Mayhem item. Spell casts grant critical strike and a shield",
        base=3.8,
        mayhem_only=True,
        job="core",
    ),
    BridgeRule(
        124011,
        frozenset({"Support", "Mage", "Battlemage"}),
        (("heal", 0.4),),
        "mayhem",
        "Mayhem item. Heal and shield power, and it heals a nearby ally on hit",
        base=3.4,
        mayhem_only=True,
    ),
    BridgeRule(3089, AP, (), "capstone", "Ability power for spells", base=1.85, job="core"),
    BridgeRule(4645, AP, (), "core", "Ability power and magic penetration for spells", base=1.6, job="core"),
    BridgeRule(4629, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power and ability haste for spells", base=1.15, job="core"),
    BridgeRule(4646, frozenset({"Mage", "Battlemage"}), (), "core", "Ability power burst for a mage", base=1.5, job="core"),
    BridgeRule(4633, frozenset({"Battlemage"}), (), "core", "Ability power and health for a battlemage", base=1.7, job="core"),
    BridgeRule(3031, frozenset({"Marksman", "Fighter"}), (), "crit", "Critical strike for auto attacks", base=1.85, job="core"),
    BridgeRule(6676, frozenset({"Marksman"}), (), "core", "Critical strike and an execute for a marksman", base=1.45, job="core"),
    BridgeRule(3094, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.35),), "zeal", "Attack speed for auto attacks", base=1.6, job="core"),
    BridgeRule(3046, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.3),), "dancer", "A second attack-speed item for auto attacks", base=1.45, job="core"),
    BridgeRule(3072, frozenset({"Marksman", "Fighter"}), (("poke", 0.85),), "lifesteal", "Lifesteal between health relics. You do not recall to heal", base=1.55, job="core"),
    BridgeRule(6672, frozenset({"Marksman", "Fighter"}), (("attack_speed", 0.25),), "core", "Attack damage and attack speed for auto attacks", base=1.5, job="core"),
    BridgeRule(3142, frozenset({"Assassin"}), (), "core", "Lethality for an assassin's abilities", base=1.7, job="core"),
    BridgeRule(6692, frozenset({"Assassin", "Fighter"}), (), "core", "Attack damage for short trades", base=1.6, job="core"),
    BridgeRule(6698, frozenset({"Assassin"}), (), "core", "Lethality and ability haste for abilities", base=1.55, job="core"),
    BridgeRule(3078, frozenset({"Fighter"}), (("attack_speed", 0.2),), "core", "Attack damage, attack speed, and ability haste for a fighter", base=1.65, job="core"),
    BridgeRule(6631, frozenset({"Fighter"}), (), "core", "Attack damage and a slow for a fighter", base=1.5, job="core"),
    BridgeRule(3161, frozenset({"Fighter", "Assassin"}), (), "core", "Ability haste and attack damage", base=1.45, job="core"),
    BridgeRule(3074, AD_BRUISER, (), "cleave", "Damage and healing for a fighter", base=1.6, job="core"),
    BridgeRule(6617, frozenset({"Support"}), (), "core", "Healing for an enchanter", base=1.8, job="core"),
    BridgeRule(3107, frozenset({"Support"}), (), "core", "A team heal for an enchanter", base=1.6, job="core"),
    BridgeRule(6616, frozenset({"Support"}), (), "core", "Ability power for an enchanter and an ally", base=1.5, job="core"),
    BridgeRule(2065, frozenset({"Support"}), (), "core", "A movespeed active for an enchanter", base=1.45, job="core"),
    BridgeRule(3504, frozenset({"Support"}), (), "core", "Attack speed for the ally an enchanter is shielding", base=1.4, job="core"),
    BridgeRule(3222, frozenset({"Support"}), (), "core", "A cleanse for an enchanter", base=1.35, job="core"),
)


@dataclass(frozen=True)
class BridgeBuyResult:
    buys: tuple[Recommendation, ...]
    threat_line: str
    detail: str
    plan: tuple[str, ...] = ()
    complete: bool = False
    focus: str = ""


@dataclass(frozen=True)
class BridgePick:
    champion: Champion
    why: str
    alternatives: tuple[str, ...]
    action: str
    rerolls: int | None
    considered: int


def _poke_value(champ: Champion) -> float:
    if champ.id in POKE_EXTRA or "Marksman" in champ.tags:
        return 1.0
    if "Mage" in champ.tags and champ.defense <= 5:
        return 0.85
    if "Mage" in champ.tags or champ.id in ENCHANTERS:
        return 0.45
    return 0.0


def bridge_threats(enemies: list[Champion], enemy_augments: tuple[str, ...] = ()) -> BridgeThreats:
    threats = BridgeThreats()
    assert threats.names is not None
    for champ in enemies:
        kind = damage_type(champ)
        weight = damage_weight(champ)
        if kind == "ad":
            threats.ad += weight
            if weight >= 0.5:
                threats.names["ad"].append(champ.name)
        elif kind == "ap":
            threats.ap += weight
            if weight >= 0.5:
                threats.names["ap"].append(champ.name)
        else:
            half = weight * 0.5
            threats.ad += half
            threats.ap += half
            if half >= 0.5:
                threats.names["ad"].append(champ.name)
                threats.names["ap"].append(champ.name)
        tank = tank_value(champ)
        threats.tank += tank
        if tank >= 0.6:
            threats.names["tank"].append(champ.name)
        if champ.id in HEAL_CHAMPS:
            threats.heal += 1
            threats.names["heal"].append(champ.name)
        tags = set(champ.tags)
        if "Marksman" in tags:
            threats.attack_speed += 1
            threats.names["attack_speed"].append(champ.name)
        if "Assassin" in tags and "Marksman" not in tags:
            threats.burst += 1
            threats.names["burst"].append(champ.name)
        poke = _poke_value(champ)
        threats.poke += poke
        if poke >= 0.8:
            threats.names["poke"].append(champ.name)
    flags = augment_flags(enemy_augments)
    if "heal" in flags:
        threats.heal += 1
        threats.names["heal"].append("an enemy augment")
    if "shield" in flags:
        threats.shield += 1
        threats.names["shield"].append("an enemy augment")
    if "armor" in flags:
        threats.tank += 0.6
        threats.names["tank"].append("an enemy augment")
    if "mr" in flags:
        threats.mr += 0.6
        threats.names["mr"].append("an enemy augment")
    return threats


def threat_line(threats: BridgeThreats) -> str:
    parts: list[str] = []
    for label, value in (
        ("AD", threats.ad),
        ("AP", threats.ap),
        ("Poke", threats.poke),
        ("Heal", threats.heal),
        ("Tank", threats.tank),
        ("Burst", threats.burst),
        ("MR", threats.mr),
    ):
        shown = round(value)
        if shown >= 1:
            parts.append(f"{label} {shown}")
    return " · ".join(parts) if parts else "No strong bridge threats"


def augment_flags(names: tuple[str, ...] | list[str]) -> set[str]:
    """Tags read from augment names and descriptions the client already sent."""
    return set(flags_from_text(*names))


def _on_bridge_shop(meta: Item | None, items: dict[int, Item]) -> bool:
    if meta is None or not meta.purchasable or not meta.in_store or not meta.howling_abyss:
        return False
    if meta.required_champion:
        return False
    if meta.id >= 10000:
        base = items.get(meta.id % 10000)
        if base is not None and base.howling_abyss and base.purchasable and base.in_store:
            return False
    return True


def _explain(rule: BridgeRule, threats: BridgeThreats) -> str:
    bits: list[str] = []
    ranked = sorted(
        ((threats.value(tag) * weight, tag) for tag, weight in rule.weights),
        reverse=True,
    )
    labels = {
        "ad": "physical damage",
        "ap": "magic damage",
        "poke": "poke",
        "heal": "healing",
        "tank": "tanks",
        "burst": "burst",
        "attack_speed": "attack speed",
        "mr": "magic resist",
        "shield": "shields",
    }
    assert threats.names is not None
    for score, tag in ranked:
        if score <= 0 or threats.value(tag) <= 0:
            continue
        names = ", ".join((threats.names.get(tag) or [])[:3])
        label = labels.get(tag, tag)
        bits.append(f"{label} vs {names}" if names else label)
        if len(bits) == 2:
            break
    if not bits:
        return rule.summary
    return f"{rule.summary} - {'; '.join(bits)}"


def _clip(names: tuple[str, ...] | list[str], limit: int) -> str:
    shown = list(names)
    text = ", ".join(shown[:limit])
    extra = len(shown) - limit
    if extra > 0:
        text += f" +{extra}"
    return text


def match_detail(
    player: tuple[str, ...] = (),
    enemy: tuple[str, ...] = (),
    *,
    exposed: bool = False,
    skipped_grievous: bool = False,
    building: str = "",
    mention_missing: bool = True,
    cards: tuple[str, ...] = (),
    absent: str = "Augments are not visible yet.",
) -> str:
    lines: list[str] = []
    if cards:
        lines.append("Augment cards on screen: " + _clip(cards, 4))
    if player:
        lines.append("Your augments: " + _clip(player, 6))
    elif mention_missing and not cards:
        if not exposed:
            lines.append(absent)
        else:
            lines.append("No augments equipped yet.")
    if enemy:
        lines.append("Enemy augments: " + _clip(enemy, 8))
    if building:
        lines.append(building)
    if skipped_grievous:
        lines.append("Skipped another grievous-wounds item.")
    return "\n".join(lines)


def shop_profile(champion: Champion, owned: dict[int, int], items: dict[int, Item]) -> str:
    """The champion's own shop profile. Owned items do not change damage type."""
    del owned, items
    return build_profile(champion)


def recommend_bridge(
    champion: Champion,
    enemies: list[Champion],
    owned: dict[int, int],
    gold: float,
    items: dict[int, Item],
    *,
    mayhem_shop: bool,
    early: bool = False,
    player_augments: tuple[str, ...] = (),
    enemy_augments: tuple[str, ...] = (),
    player_augment_text: tuple[str, ...] = (),
    enemy_augment_text: tuple[str, ...] = (),
    enemy_builds: tuple[tuple[str, tuple[int, ...]], ...] | list = (),
    augments_exposed: bool = False,
    mention_augments: bool = False,
    limit: int = 2,
    inventory_full: bool = False,
    item_labels: dict[int, str] | None = None,
    cards: tuple[str, ...] = (),
    absent: str = "Augments are not visible yet.",
) -> BridgeBuyResult:
    threats = bridge_threats(enemies, enemy_augment_text or enemy_augments)
    building = absorb_pressure(threats, enemy_builds, items)
    profile = shop_profile(champion, owned, items)
    kit = champion_kit(champion)
    flags = augment_flags(player_augment_text or player_augments)
    grievous_allow = _grievous_allow(owned)
    skipped_grievous = False
    owned_boots = _finished_boots_id(owned, items)
    owned_boot = items.get(owned_boots) if owned_boots else None
    boots_fit = owned_boot is not None and item_fits_kit(owned_boot, "boots", kit)
    item_count = sum(count for count in owned.values() if count > 0)
    scored: list[ScoredBuy] = []
    for rule in RULES:
        if profile not in rule.profiles:
            continue
        if rule.mayhem_only and not mayhem_shop:
            continue
        if rule.early_only and (not early or item_count > 1):
            continue
        owned_this = owned.get(rule.item_id, 0) > 0
        if rule.kind == "boots" and boots_fit and rule.item_id != owned_boots:
            continue
        if rule.kind == "grievous" and grievous_allow is not None and rule.item_id not in grievous_allow and not owned_this:
            continue
        if rule.kind == "shields" and threats.shield < 1:
            continue
        if rule.item_id == 124011 and champion.id not in HEAL_CHAMPS and profile != "Support":
            continue
        meta = items.get(rule.item_id)
        if not _on_bridge_shop(meta, items) or meta is None:
            continue
        if not item_fits_kit(meta, rule.kind, kit):
            continue
        ignore = _other_finished_boots(owned, items, rule.item_id) if rule.kind == "boots" else None
        if not owned_this and completion_blocked(rule.item_id, owned, items, ignore):
            continue
        score = rule.base + sum(threats.value(tag) * weight for tag, weight in rule.weights)
        score *= champion_factor(champion.id, set(meta.tags))
        if rule.kind == "shields":
            score += 2.4
        if rule.kind == "boots":
            score *= BOOTS_FACTOR
        if rule.item_id == 3065 and (champion.id in HEAL_CHAMPS or "heal" in flags):
            score += 2.2
        if rule.kind == "grievous" and "grievous" in flags:
            skipped_grievous = True
            if not owned_this:
                continue
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
        bridge=True,
        inventory_full=inventory_full,
        item_labels=item_labels,
        limit=limit,
        explain=lambda rule: _explain(rule, threats),
        kit=kit,
    )
    detail = ""
    if mention_augments or building:
        detail = match_detail(
            player_augments if mention_augments else (),
            enemy_augments if mention_augments else (),
            exposed=augments_exposed or bool(player_augments),
            skipped_grievous=skipped_grievous,
            building=building,
            mention_missing=mention_augments,
            cards=cards,
            absent=absent,
        )
    complete = bool(plan) and all(owned.get(row.item_id, 0) > 0 for row in plan)
    return BridgeBuyResult(
        tuple(buys),
        threat_line(threats),
        detail,
        tuple(row.name for row in plan),
        complete,
        kit_focus(kit),
    )


def _provides(champ: Champion) -> dict[str, float]:
    profile = build_profile(champ)
    score = {
        "poke": 0.0,
        "waveclear": 0.0,
        "frontline": 0.0,
        "engage": 0.0,
        "sustain": 0.0,
        "anti_poke": 0.0,
        "armor": 0.0,
        "mr": 0.0,
    }
    if profile == "Tank":
        score.update(frontline=3.0, engage=2.0, anti_poke=2.2, armor=2.2, mr=1.6, poke=0.2)
    elif profile == "Fighter":
        score.update(frontline=1.6, engage=1.1, poke=0.5, armor=0.7, waveclear=0.6)
    elif profile == "Assassin":
        score.update(engage=1.3, poke=0.4)
    elif profile == "Marksman":
        score.update(poke=2.5, waveclear=1.1)
    elif profile == "Mage":
        score.update(poke=2.3, waveclear=1.6)
    elif profile == "Battlemage":
        score.update(poke=1.3, waveclear=1.3, frontline=1.1, anti_poke=0.6)
    elif profile == "Support":
        score.update(sustain=2.6, poke=0.7, anti_poke=0.5)
        if "Tank" in champ.tags:
            score.update(frontline=2.2, engage=1.6, armor=1.4, mr=1.2)
    if champ.id in HEAL_CHAMPS and profile != "Support":
        score["sustain"] += 1.2
    if champ.id in POKE_EXTRA and score["poke"] < 2.0:
        score["poke"] = 2.0
    return score


def _needs(threats: BridgeThreats, allies: list[Champion]) -> dict[str, float]:
    needs = {key: 0.0 for key in ("poke", "waveclear", "frontline", "engage", "sustain", "anti_poke", "armor", "mr")}
    profiles = [build_profile(champ) for champ in allies]
    if not any(profile in {"Marksman", "Mage", "Battlemage"} for profile in profiles):
        needs["poke"] += 2.2
    else:
        needs["poke"] += 0.5
    if not any(profile == "Tank" for profile in profiles):
        needs["frontline"] += 2.2
        needs["engage"] += 1.0
    else:
        needs["frontline"] += 0.3
    if not any(build_profile(champ) == "Support" or champ.id in HEAL_CHAMPS for champ in allies):
        needs["sustain"] += 1.3
    needs["waveclear"] += 0.8
    if threats.ad >= 1:
        needs["armor"] += threats.ad
    if threats.ap >= 1:
        needs["mr"] += threats.ap
    if threats.poke >= 1:
        needs["anti_poke"] += threats.poke * 0.7
    if threats.burst >= 1:
        needs["frontline"] += threats.burst * 0.45
    return needs


_WHY = {
    "poke": "poke down the bridge",
    "waveclear": "wave clear",
    "frontline": "a frontline",
    "engage": "engage",
    "sustain": "sustain",
    "anti_poke": "staying healthy into poke",
    "armor": "armor against physical damage",
    "mr": "magic resist against spells",
}


def suggest_bridge(
    pickable: list[int],
    allies: list[Champion],
    enemies: list[Champion],
    bans: set[int],
    catalog: DragonData,
    locked_id: int = 0,
    taken_ids: set[int] | None = None,
    rerolls: int | None = None,
) -> BridgePick | None:
    taken = set(taken_ids or ())
    taken.update(champ.key for champ in allies)
    taken.update(champ.key for champ in enemies)
    taken.update(bans)
    if locked_id:
        taken.discard(locked_id)
    candidates: list[Champion] = []
    for champion_id in pickable:
        if champion_id <= 0 or champion_id in taken:
            continue
        champ = catalog.champion_by_key(champion_id)
        if champ is not None:
            candidates.append(champ)
    if not candidates:
        return None
    threats = bridge_threats(enemies)
    needs = _needs(threats, allies)
    ranked: list[tuple[float, int, str, Champion, dict[str, float]]] = []
    for champ in candidates:
        provides = _provides(champ)
        score = sum(needs[key] * provides[key] for key in needs)
        ranked.append((score, champ.defense, champ.name, champ, provides))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    score, _defense, _name, best, provides = ranked[0]
    phrases = sorted(
        ((needs[key] * provides[key], _WHY[key]) for key in needs if needs[key] and provides[key]),
        reverse=True,
    )
    if enemies:
        why = "; ".join(text for _value, text in phrases[:2]) or f"{best.name} is the best fit you can lock."
        why = f"{why[0].upper()}{why[1:]}."
    else:
        why = (
            f"No enemy champions are showing yet. {best.name} covers the holes on your side "
            "of the bridge."
        )
    action = "pick"
    if locked_id and best.key != locked_id:
        action = "bench"
    elif locked_id and best.key == locked_id:
        action = "keep"
        if rerolls and rerolls > 0 and enemies and score < REROLL_BELOW:
            action = "reroll"
            why = f"{best.name} does not cover this bridge. {why}"
    return BridgePick(
        champion=best,
        why=why,
        alternatives=tuple(row[3].name for row in ranked[1:3]),
        action=action,
        rerolls=rerolls,
        considered=len(candidates),
    )
