# How the advice is chosen

This overlay does not use win rates, tier lists, or scraped build sites. It does not call a paid API. Two local inputs (the live game, and champion select when the client allows it) are scored with the rules below. Names, stats, prices, and item recipes come from Riot Data Dragon.

## Threat tags

Each enemy champion contributes tags:

| Tag | Where it comes from |
| --- | --- |
| AD / AP / mixed | Data Dragon `info.attack` versus `info.magic`. A short override list fixes champions those bars get wrong (Qiyana, Bel'Veth, Gwen, Corki, Twisted Fate). |
| Damage weight | Carries count as 1. Tanks count as about 0.25 so a tank's damage type does not look like a second mid laner. Enchanters stay low. |
| Tank | The Tank tag, scaled by Data Dragon defense. Juggernauts with low defense count as a partial tank. |
| Heal | A curated list of kits that heal in a fight (Soraka, Aatrox, Vladimir, and the rest in `threats.py`), plus lifesteal and omnivamp items those champions have already bought. |
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

A rule is ignored when Data Dragon does not currently sell that item on Summoner's Rift, when you already finished it, or when its score is below the cutoff. A finished pair of boots blocks every other pair. Basic Boots are still upgraded into the one pair you can complete. A grievous component you already own (Bramble Vest, Executioner's Calling, Oblivion Orb) stays on that recipe instead of starting a second anti-heal item.

One-of shop rules come from the item text and the recipe, not from a win rate. Lifeline, Spellblade, Annul (the spell shield), and Quicksilver are read from the description. Last Whisper and Tear are read from the recipe. If a finished item already contains that piece, the overlay will not start the sibling: Mortal Reminder blocks Lord Dominik's Regards and Serylda's Grudge. A loose Last Whisper still finishes one of those items, and the next buy is a piece you do not already hold. The same rule applies on the bridge. Enemy armor, magic resist, healing, and shield items raise the matching buy while the game is going, so the suggestion moves as their inventory changes.

The path itself is the Data Dragon recipe. The overlay walks components you already own and picks the cheapest next step you can buy. If you can afford one, that step wins. The panel shows that component, then the completed item, then the reason with the enemy names that caused it.

Spirit Visage gets an extra bump only when you are on the heal list and the enemy team actually deals magic damage.

There is no generic "core build" when nothing counters the team. The panel says no counter buy stands out.

## Champion select

Only champions the client says you can lock are considered. Banned champions, allies, and enemies are removed. In modes that use a bench, the bench is the lock list.

Each candidate is scored by what their profile provides (frontline, armor, magic resist, peel, sustained damage, anti-tank) against what the enemy tags demand and what your allies do not already cover. A small curated list adds extra anti-tank score for kits with percent-health or true damage (Vayne, Fiora, Kog'Maw, and others in `picks.py`).

If champion select has your position, champions who normally play that lane are preferred and clear off-role picks are pushed down. Lane lists live in `roles.py`. Champions missing from that list, including brand-new ones, are not punished. If no position is set, the suggestion says it is a counter pick rather than a lane lock. When two champions score the same, the one with the higher Data Dragon defense stat is preferred, so a tankier frontliner wins a tie.

No enemy has to be visible. With an empty enemy team the suggestion fills the role and the missing ally tags, and the text says no enemies are showing yet.

## ARAM and ARAM: Mayhem

Summoner's Rift rules above are not reused for these modes. The bridge is one lane. You buy in the fountain, usually while dead, instead of recalling to a side shop. Gold from minions is higher than on Summoner's Rift. Health relics restore a share of missing health (Mayhem raises that heal from the ARAM value). Poke decides the fight before anyone all-ins. Mayhem keeps those ARAM rules and adds augments at levels 3, 7, 11, and 15, picked while the fountain shop is open. Runes are off, and every champion has Presence of Mind. Those facts are from Riot's Mayhem posts and the mode page, not from a win rate.

The live client reports Mayhem as gameMode `KIWI`. The client lobby reports it as queue 2400 (and the other Mayhem queue ids named in Community Dragon). Normal ARAM is gameMode `ARAM` or queue 450. If the map is Howling Abyss, Butcher's Bridge, or Koeshin's Crossing and neither signal is present, or champion select has a reroll count but no queue, the overlay says it cannot tell Mayhem from ARAM and still uses the ARAM shop, not the Rift shop.

Bridge buys raise grievous wounds when the enemy heals, buys lifesteal or omnivamp, or the team is mostly poke, because relics and spell healing stretch the fight. Armor they have already bought raises armor penetration. Magic resist they have already bought raises the magic-damage answer. A Lifeline item or a shield they bought allows Serpent's Fang. Tanks are pointed at health regen such as Warmog's because there is no side-lane recall. Boots stay available but rank behind a finished combat item. Finishing one counter does not end the list: a marksman who already has grievous wounds and a magic-resist item is still pointed at a legal armor-penetration item, lifesteal, or a cleanse while tanks, poke, or magic damage are on the bridge. A penetration item that shares Last Whisper with something already finished is left off that list. Mayhem's three shop legendaries (Atma's Reckoning, Rite of Ruin, Sword of Blossoming Dawn) are suggested only when the mode is certainly Mayhem. If the inventory already has two or more attack-damage or critical-strike items, a mage is shopped as a marksman for the rest of that game, and the reverse is true for a marksman stacked with ability power. The next fountain buy continues the build instead of swapping damage types. Quest rewards such as The Golden Spatula are not shop buys.

Augment ids are read from the local client. The live game API does not send them. The end-of-game screen and the saved match do, as `playerAugment` numbers for every player. Those numbers are matched to Community Dragon's Mayhem augment list so the panel can show the names. A description that says grievous skips a second grievous item. Healing, shields, armor, and magic resist in an enemy augment move the same buys as those words on an item. Until the client has recorded the match, the panel says the augments were not in the live client data. It does not invent names.

Champion select on the bridge ignores lanes. It wants poke, a frontline, and sustain for the team you can see. The bench is part of the lock list. Your current champion is kept when it scores best. A better bench champion is a swap. A reroll is suggested only when enemies are visible, rerolls remain, and the champion you have scores poorly with nothing better on the bench.

## What this is not

- Not a win rate, pick rate, or pro-build database.
- Not a full rune page or skill order.
- Not an automatic shop. It only displays the next buy.
- Summoner's Rift and the bridge use different item lists. Prices in the live shop can differ from Data Dragon.
