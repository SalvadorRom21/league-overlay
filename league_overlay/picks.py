"""Champion-select suggestion from champions the player can lock.

Scores kits against the enemy threats and the holes in the ally team.
It does not use win rates. See HEURISTIC.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from league_overlay.catalog import DragonData
from league_overlay.model import Champion
from league_overlay.roles import roles_for
from league_overlay.threats import Threats, build_profile, summarize

# Percent-health, true damage, or sustained burn into tanks.
TANK_SHRED = frozenset(
    {
        "Azir",
        "Brand",
        "Cassiopeia",
        "Fiora",
        "Gwen",
        "Kaisa",
        "Kayle",
        "KogMaw",
        "Lillia",
        "MasterYi",
        "Trundle",
        "Varus",
        "Vayne",
        "Velkoz",
    }
)

POSITIONS = {
    "top": "top",
    "jungle": "jungle",
    "middle": "middle",
    "mid": "middle",
    "bottom": "bottom",
    "bot": "bottom",
    "adc": "bottom",
    "utility": "utility",
    "support": "utility",
}

PHRASES = {
    "armor": "armor against physical damage",
    "mr": "magic resist against magic damage",
    "anti_as": "attack-speed reduction",
    "frontline": "a frontline",
    "peel": "peel",
    "dps": "sustained damage",
    "anti_tank": "damage into tanks",
    "magic": "magic damage",
    "burst_dmg": "a pick threat",
}


@dataclass(frozen=True)
class PickSuggestion:
    champion: Champion
    why: str
    alternatives: tuple[str, ...]
    considered: int
    no_enemies: bool
    position: str


def normalize_position(value: str | None) -> str:
    text = (value or "").strip().casefold()
    if text in {"", "none", "unknown"}:
        return ""
    return POSITIONS.get(text, "")


def _provides(champ: Champion) -> dict[str, float]:
    profile = build_profile(champ)
    tags = set(champ.tags)
    score = {
        "frontline": 0.0,
        "peel": 0.0,
        "armor": 0.0,
        "mr": 0.0,
        "anti_as": 0.0,
        "dps": 0.0,
        "anti_tank": 0.0,
        "magic": 0.0,
        "burst_dmg": 0.0,
    }
    if profile == "Tank":
        score.update(frontline=3.0, armor=2.2, mr=2.0, anti_as=1.6, peel=0.8)
    elif profile == "Fighter":
        score.update(frontline=1.6, dps=1.6, armor=0.8, anti_tank=0.8)
    elif profile == "Assassin":
        score.update(burst_dmg=2.2, dps=1.2, anti_tank=0.4)
    elif profile == "Marksman":
        score.update(dps=2.6, anti_tank=1.6)
    elif profile == "Mage":
        burst = 1.2 if "Assassin" in tags or champ.id in {"Annie", "Syndra", "Veigar", "Zoe"} else 0.4
        score.update(magic=2.4, anti_tank=1.3, burst_dmg=burst)
    elif profile == "Battlemage":
        score.update(frontline=1.2, magic=2.0, anti_tank=1.8, dps=1.2)
    elif profile == "Support":
        score.update(peel=2.6, mr=0.4, armor=0.4)
        if "Tank" in tags:
            score["frontline"] = 2.0
    if champ.id in TANK_SHRED:
        score["anti_tank"] += 1.8
    return score


def _needs(threats: Threats, allies: list[Champion], position: str) -> dict[str, float]:
    needs = {key: 0.0 for key in PHRASES}
    if threats.ad >= 1.5:
        needs["armor"] += threats.ad
    if threats.ap >= 1.5:
        needs["mr"] += threats.ap
    if threats.attack_speed >= 1.5:
        needs["anti_as"] += threats.attack_speed
    if threats.tank >= 1.2:
        needs["anti_tank"] += threats.tank
        needs["dps"] += 0.5 * threats.tank
    if threats.burst >= 1.5:
        needs["frontline"] += threats.burst
        needs["peel"] += 0.5 * threats.burst
    profiles = [build_profile(champ) for champ in allies]
    if not any(profile == "Tank" for profile in profiles):
        needs["frontline"] += 2.0
    if not any(profile == "Marksman" for profile in profiles):
        needs["dps"] += 1.5
    if not any(profile in {"Mage", "Battlemage"} for profile in profiles):
        needs["magic"] += 1.0
    if position == "top":
        needs["frontline"] += 1.2
    elif position == "jungle":
        needs["frontline"] += 0.6
        needs["dps"] += 0.6
    elif position == "middle":
        needs["magic"] += 1.2
        needs["burst_dmg"] += 0.8
    elif position == "bottom":
        needs["dps"] += 2.0
    elif position == "utility":
        needs["peel"] += 2.0
        needs["frontline"] += 0.8
    return needs


def _role_factor(champ_id: str, position: str) -> float:
    if not position:
        return 1.0
    lanes = roles_for(champ_id)
    if not lanes:
        return 1.0
    if position in lanes:
        return 1.25
    return 0.3


def _why(champ: Champion, needs: dict[str, float], provides: dict[str, float], position: str, no_enemies: bool) -> str:
    if no_enemies:
        role = position or "your side"
        return (
            f"No enemy champions are showing yet. {champ.name} is the closest fit "
            f"for {role} among champions you can lock."
        )
    ranked = sorted(
        ((needs[key] * provides[key], key) for key in needs if needs[key] and provides[key]),
        reverse=True,
    )
    phrases = [PHRASES[key] for _score, key in ranked[:2]]
    if not phrases:
        return f"{champ.name} is the best fit among the champions you can lock."
    detail = "; ".join(phrases)
    return f"{detail[0].upper()}{detail[1:]}."


def suggest(
    pickable: list[int],
    allies: list[Champion],
    enemies: list[Champion],
    bans: set[int],
    position: str,
    catalog: DragonData,
    locked_id: int = 0,
    taken_ids: set[int] | None = None,
) -> PickSuggestion | None:
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
    threats = summarize(enemies)
    needs = _needs(threats, allies, position)
    no_enemies = not enemies
    ranked: list[tuple[float, float, int, str, Champion, dict[str, float]]] = []
    for champ in candidates:
        provides = _provides(champ)
        raw = sum(needs[key] * provides[key] for key in needs)
        factor = _role_factor(champ.id, position)
        ranked.append((raw * factor, factor, champ.defense, champ.name, champ, provides))
    ranked.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
    _score, _factor, _defense, _name, best, provides = ranked[0]
    alternatives = tuple(row[4].name for row in ranked[1:3])
    return PickSuggestion(
        champion=best,
        why=_why(best, needs, provides, position, no_enemies),
        alternatives=alternatives,
        considered=len(candidates),
        no_enemies=no_enemies,
        position=position,
    )
