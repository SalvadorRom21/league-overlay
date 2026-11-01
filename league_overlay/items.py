"""Next shop step against the enemy team.

Completed items are a fixed list of Summoner's Rift answers (armor, magic
resist, grievous wounds, penetration, anti-burst). Names, prices, and the
component recipe come from Data Dragon at runtime. If a patch removes an item,
that rule is skipped. See HEURISTIC.md.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from league_overlay.model import Champion, Item
from league_overlay.threats import HEAL_CHAMPS, Threats, build_profile, summarize

MIN_SCORE = 1.6

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
}

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


RULES: tuple[ItemRule, ...] = (
    ItemRule(3047, ALL, (("ad", 1.35), ("attack_speed", 1.1)), "boots", "Armor boots"),
    ItemRule(3111, ALL, (("ap", 1.35), ("burst", 0.55)), "boots", "Magic resist boots and tenacity"),
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
    ItemRule(3068, frozenset({"Tank"}), (("ad", 1.05),), "armor", "Armor and a burn aura"),
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
    ItemRule(6664, frozenset({"Tank"}), (("ap", 1.1),), "mr", "Magic resist and a burn aura"),
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
    ItemRule(3135, AP, (("tank", 1.7),), "pen", "Magic penetration"),
    ItemRule(3137, AP, (("tank", 1.45),), "pen", "Magic penetration"),
    ItemRule(6653, AP, (("tank", 1.65),), "pen", "A max-health burn"),
    ItemRule(8010, frozenset({"Mage", "Battlemage"}), (("tank", 1.4),), "pen", "Magic resist shred"),
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
    for item_id, count in owned.items():
        if count <= 0:
            continue
        meta = items.get(item_id)
        if meta is not None and "Boots" in meta.tags:
            return True
    return False


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


def recommend(
    champion: Champion,
    enemies: list[Champion],
    owned: dict[int, int],
    gold: float,
    items: dict[int, Item],
    limit: int = 2,
) -> list[Recommendation]:
    """Up to `limit` buy paths, best counter first."""
    threats = summarize(enemies)
    profile = build_profile(champion)
    grievous_allow = _grievous_allow(owned)
    boots_owned = _owns_boots(owned, items)
    scored: list[tuple[float, int, ItemRule]] = []
    for rule in RULES:
        if profile not in rule.profiles:
            continue
        if rule.kind == "boots" and boots_owned:
            continue
        if rule.kind == "grievous" and grievous_allow is not None and rule.item_id not in grievous_allow:
            continue
        meta = items.get(rule.item_id)
        if not _shop_item(meta):
            continue
        if owned.get(rule.item_id, 0) > 0:
            continue
        score = sum(threats.value(tag) * weight for tag, weight in rule.weights)
        if rule.item_id == 3065 and champion.id in HEAL_CHAMPS and threats.ap >= 1:
            score += 1.8
        if score < MIN_SCORE:
            continue
        scored.append((score, rule.item_id, rule))
    scored.sort(key=lambda row: (-row[0], row[1]))
    picks: list[Recommendation] = []
    seen_kinds: set[str] = set()
    for _score, _item_id, rule in scored:
        if rule.kind in seen_kinds:
            continue
        step = next_purchase(rule.item_id, owned, gold, items)
        if step is None:
            continue
        buy_id, cost, combine = step
        buy = items.get(buy_id)
        completed = items.get(rule.item_id)
        if buy is None or completed is None:
            continue
        short = 0 if gold >= cost else max(1, math.ceil(cost - gold))
        picks.append(
            Recommendation(
                completed_id=completed.id,
                completed_name=completed.name,
                completed_total=completed.total,
                buy_id=buy.id,
                buy_name=buy.name,
                cost=cost,
                combine=combine,
                affordable=gold >= cost,
                gold_short=short,
                why=_explain(rule, threats),
                kind=rule.kind,
                have=_owned_names(completed.id, owned, items),
            )
        )
        seen_kinds.add(rule.kind)
        if len(picks) >= limit:
            break
    return picks
