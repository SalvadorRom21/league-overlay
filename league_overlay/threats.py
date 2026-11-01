"""Turn enemy champions into threat tags.

This is a documented heuristic, not a win-rate model. Damage type comes from
Data Dragon's attack/magic info, with a few overrides where those numbers
disagree with what the champion deals. Healing, attack speed, and burst are
curated from kits. See HEURISTIC.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from league_overlay.model import Champion

# Data Dragon's attack/magic bars mislabel these kits.
DAMAGE_OVERRIDE = {
    "Belveth": "ad",
    "Corki": "ap",
    "Gwen": "ap",
    "Qiyana": "ad",
    "TwistedFate": "ap",
}

# Shop profile when tags alone would pick the wrong item set.
PROFILE_OVERRIDE = {
    "Ambessa": "Fighter",
    "Fizz": "Mage",
    "Jayce": "Fighter",
    "KSante": "Tank",
    "Naafiri": "Assassin",
    "Nilah": "Marksman",
    "Rengar": "Assassin",
    "Swain": "Battlemage",
}

ENCHANTERS = frozenset(
    {
        "Ivern",
        "Janna",
        "Karma",
        "Lulu",
        "Milio",
        "Nami",
        "Renata",
        "Seraphine",
        "Sona",
        "Soraka",
        "Yuumi",
    }
)

# Champions whose kits heal during a fight. Used for grievous-wounds advice.
HEAL_CHAMPS = frozenset(
    {
        "Aatrox",
        "Bard",
        "Belveth",
        "Briar",
        "Darius",
        "DrMundo",
        "Fiddlesticks",
        "Fiora",
        "Gragas",
        "Illaoi",
        "Irelia",
        "Ivern",
        "Karma",
        "Kayn",
        "LeeSin",
        "Maokai",
        "MasterYi",
        "Milio",
        "Nami",
        "Nasus",
        "Nidalee",
        "Nunu",
        "Olaf",
        "Rakan",
        "Renekton",
        "Senna",
        "Seraphine",
        "Sona",
        "Soraka",
        "Swain",
        "Sylas",
        "Taric",
        "Vladimir",
        "Volibear",
        "Warwick",
        "XinZhao",
        "Yuumi",
        "Zac",
    }
)

# Auto-attack threats that are not tagged Marksman.
AS_EXTRA = frozenset(
    {
        "Belveth",
        "Gnar",
        "Gwen",
        "Irelia",
        "Jax",
        "Kayle",
        "MasterYi",
        "Nilah",
        "Nocturne",
        "Olaf",
        "Tryndamere",
        "Udyr",
        "Viego",
        "Warwick",
        "XinZhao",
        "Yasuo",
        "Yone",
    }
)

# Burst that the Assassin tag does not already cover.
BURST_EXTRA = frozenset(
    {
        "Anivia",
        "Annie",
        "Aurora",
        "Brand",
        "Diana",
        "Hwei",
        "Kennen",
        "Lissandra",
        "Lux",
        "Malphite",
        "Neeko",
        "Syndra",
        "TwistedFate",
        "Veigar",
        "Velkoz",
        "Vex",
        "Xerath",
        "Ziggs",
        "Zoe",
    }
)

PROFILES = (
    "Tank",
    "Fighter",
    "Assassin",
    "Marksman",
    "Mage",
    "Battlemage",
    "Support",
)


@dataclass
class Threats:
    ad: float = 0.0
    ap: float = 0.0
    tank: float = 0.0
    heal: float = 0.0
    attack_speed: float = 0.0
    burst: float = 0.0
    names: dict[str, list[str]] = field(default_factory=dict)

    def value(self, tag: str) -> float:
        return float(getattr(self, tag))


def _names() -> dict[str, list[str]]:
    return {key: [] for key in ("ad", "ap", "tank", "heal", "attack_speed", "burst")}


def damage_type(champ: Champion) -> str:
    """Return 'ad', 'ap', or 'mixed'."""
    forced = DAMAGE_OVERRIDE.get(champ.id)
    if forced:
        return forced
    attack, magic = champ.attack, champ.magic
    if attack == 0 and magic == 0:
        tags = set(champ.tags)
        if "Mage" in tags and "Marksman" not in tags:
            return "ap"
        if tags.intersection({"Marksman", "Assassin", "Fighter"}):
            return "ad"
        return "mixed"
    if magic > attack:
        return "ap"
    if attack > magic:
        return "ad"
    return "mixed"


def build_profile(champ: Champion) -> str:
    """Which item set this champion shops. See HEURISTIC.md."""
    forced = PROFILE_OVERRIDE.get(champ.id)
    if forced:
        return forced
    tags = set(champ.tags)
    if champ.id in ENCHANTERS:
        return "Support"
    if "Tank" in tags and "Marksman" not in tags:
        if champ.attack == 0 and champ.magic == 0 and champ.defense == 0:
            return "Tank"
        mage_carry = "Mage" in tags and champ.magic >= champ.defense and champ.magic >= 8
        bulky = champ.defense >= 6 and (champ.attack <= 7 or champ.defense >= champ.attack)
        if not mage_carry and bulky:
            return "Tank"
    kind = damage_type(champ)
    if "Marksman" in tags and kind != "ap":
        return "Marksman"
    if kind == "ap" and "Fighter" in tags:
        return "Battlemage"
    if kind == "ap" and "Mage" in tags and "Support" in tags:
        if champ.defense <= 4 and champ.magic >= 8:
            return "Mage"
        return "Support"
    if kind == "ap" and "Mage" in tags:
        return "Mage"
    if "Assassin" in tags and ("Fighter" not in tags or champ.defense <= 3):
        return "Assassin"
    if "Fighter" in tags:
        return "Fighter"
    if "Tank" in tags:
        return "Tank"
    if "Support" in tags:
        return "Support"
    if "Mage" in tags:
        return "Mage"
    return "Fighter"


def damage_weight(champ: Champion) -> float:
    """How much of the enemy's damage this champion is. Tanks count less than carries."""
    if champ.id in ENCHANTERS:
        return 0.2
    tags = set(champ.tags)
    if "Marksman" in tags or "Assassin" in tags:
        return 1.0
    if "Mage" in tags and "Tank" not in tags and "Support" not in tags:
        return 1.0
    if "Mage" in tags and "Support" in tags and champ.magic >= 8 and champ.defense <= 4:
        return 1.0
    if "Mage" in tags and "Support" in tags and champ.magic >= 8:
        return 0.75
    if "Fighter" in tags and "Tank" not in tags:
        return 1.0
    if "Fighter" in tags and "Tank" in tags and max(champ.attack, champ.magic) >= 8:
        return 0.85
    if "Tank" in tags:
        return 0.25
    if "Support" in tags:
        return 0.2
    return 0.5


def tank_value(champ: Champion) -> float:
    if "Tank" not in champ.tags:
        return 0.0
    if champ.defense >= 8 or (champ.defense >= 6 and champ.attack <= 6):
        return 1.0
    if champ.defense >= 6:
        return 0.6
    return 0.4


def summarize(champions: list[Champion]) -> Threats:
    threats = Threats(names=_names())
    for champ in champions:
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
        if "Marksman" in tags or champ.id in AS_EXTRA:
            threats.attack_speed += 1
            threats.names["attack_speed"].append(champ.name)
        if champ.id in BURST_EXTRA or ("Assassin" in tags and "Marksman" not in tags):
            threats.burst += 1
            threats.names["burst"].append(champ.name)
    return threats


def threat_line(threats: Threats) -> str:
    parts: list[str] = []
    for label, value in (
        ("AD", threats.ad),
        ("AP", threats.ap),
        ("Tank", threats.tank),
        ("Heal", threats.heal),
        ("AS", threats.attack_speed),
        ("Burst", threats.burst),
    ):
        shown = round(value)
        if shown >= 1:
            parts.append(f"{label} {shown}")
    return " · ".join(parts) if parts else "No strong threats"
