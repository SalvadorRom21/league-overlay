# How the advice is chosen

This overlay does not use win rates, tier lists, or scraped build sites. It does not call a paid API. Two local inputs (the live game, and champion select when the client allows it) are scored with the rules below. Names, stats, prices, and item recipes come from Riot Data Dragon.

## Threat tags

Each enemy champion contributes tags:

| Tag | Where it comes from |
| --- | --- |
| AD / AP / mixed | Data Dragon `info.attack` versus `info.magic`. A short override list fixes champions those bars get wrong (Qiyana, Bel'Veth, Gwen, Corki, Twisted Fate). |
| Damage weight | Carries count as 1. Tanks count as about 0.25 so a tank's damage type does not look like a second mid laner. Enchanters stay low. |
| Tank | The Tank tag, scaled by Data Dragon defense. Juggernauts with low defense count as a partial tank. |
| Heal | A curated list of kits that heal in a fight (Soraka, Aatrox, Vladimir, and the rest in `threats.py`). This is not lifesteal-from-items and not a win rate. |
| Attack speed | Marksman tag, plus melee auto-attackers such as Yasuo, Yone, Jax, and Master Yi. |
| Burst | Assassin tag (except marksmen who are also tagged Assassin), plus burst mages such as Syndra, Annie, and Zoe. |

The in-game panel shows the rounded totals: `AD 3 · AP 1 · Heal 1`.

## Who you are shopping as

Your champion is placed in one shop profile: Tank, Fighter, Assassin, Marksman, Mage, Battlemage, or Support. The profile comes from Data Dragon tags, with overrides where the tags would buy the wrong stats (Fizz shops as a mage, Nilah as a marksman, Jayce as a fighter, K'Sante as a tank).

## What it tells you to buy

`items.py` holds a list of completed Summoner's Rift items. Each one says which profiles buy it, which threat tags raise its score, and a one-line reason. Examples:

- Plated Steelcaps when physical damage and attack speed are high.
- Mercury's Treads when magic damage is high.
- Thornmail, Mortal Reminder, Chempunk Chainsword, or Morellonomicon when the enemy team heals. The item depends on your profile.
- Lord Dominik's Regards, Black Cleaver, Void Staff, Liandry's, and similar items when the enemy team is tanky.
- Zhonya's, Guardian Angel, Sterak's, Shieldbow, or Edge of Night into burst.

A rule is ignored when Data Dragon does not currently sell that item on Summoner's Rift, when you already finished it, or when its score is below the cutoff. Boots are suggested only if you do not already own boots. A grievous component you already own (Bramble Vest, Executioner's Calling, Oblivion Orb) stays on that recipe instead of starting a second anti-heal item.

The path itself is the Data Dragon recipe. The overlay walks components you already own and picks the cheapest next step you can buy. If you can afford one, that step wins. The panel shows that component, then the completed item, then the reason with the enemy names that caused it.

Spirit Visage gets an extra bump only when you are on the heal list and the enemy team actually deals magic damage.

There is no generic "core build" when nothing counters the team. The panel says no counter buy stands out.

## Champion select

Only champions the client says you can lock are considered. Banned champions, allies, and enemies are removed. In modes that use a bench, the bench is the lock list.

Each candidate is scored by what their profile provides (frontline, armor, magic resist, peel, sustained damage, anti-tank) against what the enemy tags demand and what your allies do not already cover. A small curated list adds extra anti-tank score for kits with percent-health or true damage (Vayne, Fiora, Kog'Maw, and others in `picks.py`).

If champion select has your position, champions who normally play that lane are preferred and clear off-role picks are pushed down. Lane lists live in `roles.py`. Champions missing from that list, including brand-new ones, are not punished. If no position is set, the suggestion says it is a counter pick rather than a lane lock. When two champions score the same, the one with the higher Data Dragon defense stat is preferred, so a tankier frontliner wins a tie.

No enemy has to be visible. With an empty enemy team the suggestion fills the role and the missing ally tags, and the text says no enemies are showing yet.

## What this is not

- Not a win rate, pick rate, or pro-build database.
- Not a full rune page or skill order.
- Not an automatic shop. It only displays the next buy.
- Tuned around Summoner's Rift items. ARAM prices and stocks can differ; the panel still won't crash.
