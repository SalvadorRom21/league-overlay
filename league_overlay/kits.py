"""What each champion spends gold on.

Styles are kit facts: a burn mage wants a burn, a spell marksman wants ability
haste, a locked attack speed sinks attack-speed items. This is not a win rate
and not a build site. A champion missing from the table falls back to the
tag profile in threats.py.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

LIANDRY = 6653
RYLAI = 3116
NASHOR = 3115
LICH = 3100
ROA = 6657
RIFT = 4633
GUINSOO = 3124
MANAMUNE = 3004
SHOJIN = 3161
CLEAVER = 3071
TRINITY = 3078
IE = 3031
RFC = 3094
PD = 3046
KRAKEN = 6672
LUDEN = 6655
STORM = 4646


@dataclass(frozen=True)
class Style:
    shop: str
    damage: str
    pattern: str
    role: str
    focus: str = ""
    prefs: tuple[tuple[str, float], ...] = ()
    cores: frozenset[int] = frozenset()
    item_mult: tuple[tuple[int, float], ...] = ()
    boots: bool = True


def _prefs(**values: float) -> tuple[tuple[str, float], ...]:
    return tuple(sorted(values.items()))


def _mult(values: dict[int, float]) -> tuple[tuple[int, float], ...]:
    return tuple(sorted(values.items()))


STYLES: dict[str, Style] = {
    "burst": Style("Mage", "ap", "spell", "Mage", prefs=_prefs(ap=1.1, haste=1.08)),
    "dot": Style(
        "Mage",
        "ap",
        "spell",
        "Mage",
        "ability power on damage over time",
        _prefs(ap=1.15, haste=1.15),
        frozenset({LIANDRY}),
        _mult({LUDEN: 0.35, STORM: 0.4, RYLAI: 1.35}),
    ),
    "battle": Style(
        "Battlemage",
        "ap",
        "both",
        "Battlemage",
        "ability power and health",
        _prefs(ap=1.15, haste=1.15),
        frozenset({RIFT, ROA}),
        _mult({LUDEN: 0.35, STORM: 0.4}),
    ),
    "ap_assassin": Style(
        "Mage",
        "ap",
        "spell",
        "Mage",
        "ability power on a short trade",
        _prefs(ap=1.2, haste=1.35),
        frozenset({LICH}),
        _mult({LUDEN: 0.55, STORM: 0.7}),
    ),
    "ap_auto": Style(
        "Mage",
        "ap",
        "auto",
        "Mage",
        "ability power on auto attacks",
        _prefs(ap=1.15, attack_speed=1.4, haste=1.1),
        frozenset({NASHOR}),
        _mult({LUDEN: 0.7}),
    ),
    "enchanter": Style("Support", "ap", "spell", "Enchanter"),
    "tank": Style("Tank", "tank", "both", "Tank"),
    "bruiser": Style(
        "Fighter",
        "ad",
        "both",
        "Fighter",
        "attack damage and ability haste",
        _prefs(ad=1.15, haste=1.2, attack_speed=0.85, crit=0.55),
    ),
    "juggernaut": Style(
        "Fighter",
        "ad",
        "both",
        "Fighter",
        "attack damage and health",
        _prefs(ad=1.2, haste=1.15, attack_speed=0.9, crit=0.45),
        frozenset({CLEAVER}),
    ),
    "crit_melee": Style(
        "Fighter",
        "ad",
        "auto",
        "Fighter",
        "critical strike on auto attacks",
        _prefs(crit=1.4, attack_speed=1.15, ad=1.1),
        frozenset({IE}),
    ),
    "skirmisher": Style(
        "Fighter",
        "ad",
        "both",
        "Fighter",
        "attack damage and attack speed",
        _prefs(attack_speed=1.3, ad=1.15, haste=1.1, crit=0.55),
        frozenset({3153}),
    ),
    "crit_marksman": Style(
        "Marksman",
        "ad",
        "auto",
        "Marksman",
        prefs=_prefs(crit=1.2, ad=1.05),
        cores=frozenset({IE}),
        item_mult=_mult({SHOJIN: 0.45, MANAMUNE: 0.7}),
    ),
    "onhit": Style(
        "Marksman",
        "ad",
        "auto",
        "Marksman",
        "attack speed and on-hit damage",
        _prefs(attack_speed=1.45, crit=0.7, ad=1.1),
        frozenset({GUINSOO}),
        _mult({IE: 0.5}),
    ),
    "spell_adc": Style(
        "Marksman",
        "ad",
        "spell",
        "Marksman",
        "attack damage and ability haste on spell casts",
        _prefs(crit=0.4, attack_speed=0.45, ad=1.25, haste=1.5),
        frozenset({MANAMUNE, SHOJIN}),
        _mult({IE: 0.45, RFC: 0.3, PD: 0.3, KRAKEN: 0.35}),
    ),
    "crit_caster": Style(
        "Marksman",
        "ad",
        "auto",
        "Marksman",
        "critical strike without attack speed",
        _prefs(crit=1.3, attack_speed=0.5, ad=1.15, lethality=1.25, haste=1.15),
        item_mult=_mult({RFC: 0.4, PD: 0.4, KRAKEN: 0.45}),
    ),
    "caster": Style(
        "Fighter",
        "ad",
        "spell",
        "Fighter",
        "attack damage and ability haste on spell casts",
        _prefs(lethality=1.4, haste=1.45, attack_speed=0.35, ad=1.2, crit=0.4),
        frozenset({SHOJIN}),
        _mult({TRINITY: 0.3, IE: 0.3, RFC: 0.3}),
    ),
    "ad_assassin": Style(
        "Assassin",
        "ad",
        "spell",
        "Assassin",
        "lethality on abilities",
        _prefs(lethality=1.35, haste=1.3, ad=1.15, attack_speed=0.6, crit=0.5),
    ),
}


# Every champion in the current Data Dragon table. The value is a style name.
CHAMP_STYLES: dict[str, str] = {
    "Aatrox": "bruiser",
    "Ahri": "burst",
    "Akali": "ap_assassin",
    "Akshan": "crit_marksman",
    "Alistar": "tank",
    "Ambessa": "bruiser",
    "Amumu": "tank",
    "Anivia": "battle",
    "Annie": "burst",
    "Aphelios": "crit_marksman",
    "Ashe": "crit_marksman",
    "AurelionSol": "battle",
    "Aurora": "burst",
    "Azir": "ap_auto",
    "Bard": "burst",
    "Belveth": "skirmisher",
    "Blitzcrank": "tank",
    "Brand": "dot",
    "Braum": "tank",
    "Briar": "bruiser",
    "Caitlyn": "crit_marksman",
    "Camille": "bruiser",
    "Cassiopeia": "dot",
    "Chogath": "tank",
    "Corki": "crit_marksman",
    "Darius": "juggernaut",
    "Diana": "ap_assassin",
    "DrMundo": "tank",
    "Draven": "crit_marksman",
    "Ekko": "ap_assassin",
    "Elise": "ap_assassin",
    "Evelynn": "ap_assassin",
    "Ezreal": "spell_adc",
    "Fiddlesticks": "burst",
    "Fiora": "bruiser",
    "Fizz": "ap_assassin",
    "Galio": "battle",
    "Gangplank": "crit_melee",
    "Garen": "juggernaut",
    "Gnar": "skirmisher",
    "Gragas": "battle",
    "Graves": "crit_caster",
    "Gwen": "ap_auto",
    "Hecarim": "bruiser",
    "Heimerdinger": "burst",
    "Hwei": "burst",
    "Illaoi": "juggernaut",
    "Irelia": "skirmisher",
    "Ivern": "enchanter",
    "Janna": "enchanter",
    "JarvanIV": "juggernaut",
    "Jax": "skirmisher",
    "Jayce": "caster",
    "Jhin": "crit_caster",
    "Jinx": "crit_marksman",
    "KSante": "tank",
    "Kaisa": "onhit",
    "Kalista": "onhit",
    "Karma": "burst",
    "Karthus": "burst",
    "Kassadin": "battle",
    "Katarina": "ap_assassin",
    "Kayle": "ap_auto",
    "Kayn": "bruiser",
    "Kennen": "burst",
    "Khazix": "ad_assassin",
    "Kindred": "crit_marksman",
    "Kled": "bruiser",
    "KogMaw": "onhit",
    "Leblanc": "burst",
    "LeeSin": "bruiser",
    "Leona": "tank",
    "Lillia": "dot",
    "Lissandra": "burst",
    "Locke": "ad_assassin",
    "Lucian": "crit_caster",
    "Lulu": "enchanter",
    "Lux": "burst",
    "Malphite": "tank",
    "Malzahar": "dot",
    "Maokai": "tank",
    "MasterYi": "crit_melee",
    "Mel": "burst",
    "Milio": "enchanter",
    "MissFortune": "crit_caster",
    "MonkeyKing": "bruiser",
    "Mordekaiser": "battle",
    "Morgana": "burst",
    "Naafiri": "ad_assassin",
    "Nami": "enchanter",
    "Nasus": "juggernaut",
    "Nautilus": "tank",
    "Neeko": "burst",
    "Nidalee": "ap_assassin",
    "Nilah": "crit_marksman",
    "Nocturne": "skirmisher",
    "Nunu": "tank",
    "Olaf": "skirmisher",
    "Orianna": "burst",
    "Ornn": "tank",
    "Pantheon": "bruiser",
    "Poppy": "tank",
    "Pyke": "ad_assassin",
    "Qiyana": "ad_assassin",
    "Quinn": "crit_marksman",
    "Rakan": "burst",
    "Rammus": "tank",
    "RekSai": "bruiser",
    "Rell": "tank",
    "Renata": "enchanter",
    "Renekton": "bruiser",
    "Rengar": "ad_assassin",
    "Riven": "bruiser",
    "Rumble": "battle",
    "Ryze": "battle",
    "Samira": "crit_marksman",
    "Sejuani": "tank",
    "Senna": "crit_caster",
    "Seraphine": "enchanter",
    "Sett": "juggernaut",
    "Shaco": "ad_assassin",
    "Shen": "tank",
    "Shyvana": "battle",
    "Singed": "dot",
    "Sion": "tank",
    "Sivir": "crit_marksman",
    "Skarner": "tank",
    "Smolder": "spell_adc",
    "Sona": "enchanter",
    "Soraka": "enchanter",
    "Swain": "battle",
    "Sylas": "battle",
    "Syndra": "burst",
    "TahmKench": "tank",
    "Taliyah": "burst",
    "Talon": "ad_assassin",
    "Taric": "tank",
    "Teemo": "ap_auto",
    "Thresh": "tank",
    "Tristana": "crit_marksman",
    "Trundle": "juggernaut",
    "Tryndamere": "crit_melee",
    "TwistedFate": "burst",
    "Twitch": "crit_marksman",
    "Udyr": "skirmisher",
    "Urgot": "juggernaut",
    "Varus": "onhit",
    "Vayne": "onhit",
    "Veigar": "burst",
    "Velkoz": "burst",
    "Vex": "burst",
    "Vi": "bruiser",
    "Viego": "skirmisher",
    "Viktor": "burst",
    "Vladimir": "battle",
    "Volibear": "juggernaut",
    "Warwick": "skirmisher",
    "Xayah": "crit_marksman",
    "Xerath": "burst",
    "XinZhao": "skirmisher",
    "Yasuo": "crit_melee",
    "Yone": "crit_melee",
    "Yorick": "juggernaut",
    "Yunara": "crit_marksman",
    "Yuumi": "enchanter",
    "Zaahen": "bruiser",
    "Zac": "tank",
    "Zed": "ad_assassin",
    "Zeri": "crit_marksman",
    "Ziggs": "burst",
    "Zilean": "burst",
    "Zoe": "burst",
    "Zyra": "dot",
}


# Kits that differ from the rest of their style.
OVERRIDES: dict[str, dict[str, object]] = {
    "Jhin": {
        "prefs": _prefs(crit=1.8, ad=1.1, lethality=1.35, attack_speed=0.4, lifesteal=0.65),
        "focus": "attack damage and crit. Bonus attack speed becomes a little attack damage",
    },
    "Graves": {
        "prefs": _prefs(crit=1.25, ad=1.15, lethality=1.3, attack_speed=0.45),
        "focus": "attack damage and crit between reloads",
    },
    "Kalista": {"focus": "attack speed on spears"},
    "Zilean": {
        "prefs": _prefs(ap=1.2, haste=1.5),
        "focus": "ability power and ability haste on bombs. The rewind does not scale with heal power",
    },
    "Karma": {
        "prefs": _prefs(ap=1.2, haste=1.25),
        "focus": "ability power on mantra",
    },
    "Heimerdinger": {"focus": "ability power on turrets"},
    "Taliyah": {"focus": "ability power on rocks"},
    "Morgana": {"focus": "ability power on the pool and the binding"},
    "Bard": {"focus": "ability power on meeps"},
    "Rakan": {"focus": "ability power on the engage"},
    "Cassiopeia": {
        "boots": False,
        "focus": "ability power on poison. Boots do not fit this champion",
    },
    "Teemo": {
        "cores": frozenset({LIANDRY}),
        "focus": "ability power on shrooms and darts",
    },
    "Urgot": {"item_mult": {TRINITY: 0.3}},
    "Corki": {"focus": "critical strike. The package turns attack damage into magic damage"},
    "Gwen": {"shop": "Battlemage", "role": "Battlemage"},
    "Shyvana": {"focus": "ability power on the dragon breath"},
}


def style_for(champ_id: str) -> Style | None:
    """The kit style for this champion, or None when the table has no row."""
    key = CHAMP_STYLES.get(champ_id)
    if key is None:
        return None
    style = STYLES[key]
    extra = OVERRIDES.get(champ_id)
    if not extra:
        return style
    cores = style.cores | frozenset(extra.get("cores", ()))
    mult = dict(style.item_mult)
    mult.update(extra.get("item_mult", {}))
    return replace(
        style,
        shop=extra.get("shop", style.shop),
        damage=extra.get("damage", style.damage),
        pattern=extra.get("pattern", style.pattern),
        role=extra.get("role", style.role),
        focus=extra.get("focus", style.focus),
        prefs=extra.get("prefs", style.prefs),
        cores=cores,
        item_mult=tuple(sorted(mult.items())),
        boots=extra.get("boots", style.boots),
    )
