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

The six-item plan starts from that champion. Damage is attack damage, ability power, or tank. Pattern is auto attacks, spells, or both. A mage is not handed attack-damage items, a marksman is not handed ability-power items, and a tank's slots stay on health and resists. Heal and shield items are for a champion whose spells scale with that power, such as Soraka, Lulu, and Nami. Every champion has a kit style: burst mage, burn mage, battle mage, enchanter, tank, bruiser, juggernaut, crit marksman, on-hit marksman, spell marksman, and the rest of the table in `kits.py`. The six items follow that style, so a burn mage is not handed the same plan as a burst mage and a spell marksman is not handed attack speed. A Support tag is the lane. Zilean's rewind does not scale with heal power, and Cassiopeia does not buy boots. A few kits do not use the usual stat for that role: Jhin's attack speed is locked and turns into a little attack damage, so his slots stay on critical strike and attack damage. At least three of the six slots stay on the finished items that kit scales with. The other slots are the armor, magic resist, grievous, or penetration version that same champion can use against the live enemies. One magic-resist item is enough. A second one does not replace a damage item his kit scales with.

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

The six item slots are one plan for this champion in this match. Boots stay in that plan. Boots in the plan are the pair that champion wears: magic penetration for spells, attack speed for auto attacks, ability haste for an assassin's abilities, and armor or magic resist when that damage is the threat. Once he owns a finished pair, the panel also names one boots-sell item: the next finished item that fits his kit and this fight, bought by selling those boots. The line says later until the other five planned items are finished, which is a full build, including when the gold is already high. Then the next buy is that sell, and it names the boots. A finished pair he already owns stays when it fits him. A pair that does not fit can be sold for the pair that does. The trinket does not take a slot. The plan then fills with his finished items and the counters he can use: enemy champions, the items they already bought, his items, and augments when the screen reader has them. A slot that already holds a component is finished into that plan, or sold for the planned item when the component does not build into it. An open slot is named on the next buy. When all six slots are full, the next buy still names one owned item to sell if a planned item is not in the inventory yet. The sell is a piece outside the plan when one exists, otherwise the piece that least matches this champion and the live game. A finished item that fits his damage type is not sold to buy a counter he cannot use. The item just recommended, and anything he does not own, stay put.

Spirit Visage gets an extra bump only when you are on the heal list and the enemy team actually deals magic damage.

When the enemy team does not demand a counter, the remaining slots stay on that champion's own finished items. The panel says no buy stands out only when the shop has nothing he can use.

## Champion select

Only champions the client says you can lock are considered. Banned champions, allies, and enemies are removed. In modes that use a bench, the bench is the lock list.

Each candidate is scored by what their profile provides (frontline, armor, magic resist, peel, sustained damage, anti-tank) against what the enemy tags demand and what your allies do not already cover. A small curated list adds extra anti-tank score for kits with percent-health or true damage (Vayne, Fiora, Kog'Maw, and others in `picks.py`).

If champion select has your position, champions who normally play that lane are preferred and clear off-role picks are pushed down. Lane lists live in `roles.py`. Champions missing from that list, including brand-new ones, are not punished. If no position is set, the suggestion says it is a counter pick rather than a lane lock. When two champions score the same, the one with the higher Data Dragon defense stat is preferred, so a tankier frontliner wins a tie.

No enemy has to be visible. With an empty enemy team the suggestion fills the role and the missing ally tags, and the text says no enemies are showing yet.

## ARAM and ARAM: Mayhem

Summoner's Rift rules above are not reused for these modes. The bridge is one lane. You buy in the fountain, usually while dead, instead of recalling to a side shop. Gold from minions is higher than on Summoner's Rift. Health relics restore a share of missing health (Mayhem raises that heal from the ARAM value). Poke decides the fight before anyone all-ins. Mayhem keeps those ARAM rules and adds augments at levels 3, 7, 11, and 15, picked while the fountain shop is open. Runes are off, and every champion has Presence of Mind. Those facts are from Riot's Mayhem posts and the mode page, not from a win rate.

The live client reports Mayhem as gameMode `KIWI`. The client lobby reports it as queue 2400 (and the other Mayhem queue ids named in Community Dragon). Normal ARAM is gameMode `ARAM` or queue 450. If the map is Howling Abyss, Butcher's Bridge, or Koeshin's Crossing and neither signal is present, or champion select has a reroll count but no queue, the overlay says it cannot tell Mayhem from ARAM and still uses the ARAM shop, not the Rift shop.

The bridge fight is already going, so the plan spends four of the six slots on items that deal damage in that fight. One slot is boots. One answers healing, tanks, or burst. Rod of Ages stays out because it spends the first fights stacking. A marksman takes Runaan's Hurricane for the champions standing together, and Infinity Edge for the damage. Bridge buys raise grievous wounds when the enemy heals, buys lifesteal or omnivamp, or the team is mostly poke, because relics and spell healing stretch the fight. Armor they have already bought raises armor penetration. Magic resist they have already bought raises the magic-damage answer. A Lifeline item or a shield they bought allows Serpent's Fang. Tanks are pointed at health regen such as Warmog's because there is no side-lane recall. Boots stay available but rank behind a finished combat item, and they count as one of the six slots. The plan keeps going until six finished items fit the live game. A component already in a slot is finished when it builds into that plan. An empty slot is named on the next buy. A full inventory names a sell when a planned item is still missing. A penetration item that shares Last Whisper with something already finished is left off that list. Mayhem's three shop legendaries (Atma's Reckoning, Rite of Ruin, Sword of Blossoming Dawn) are suggested only when the mode is certainly Mayhem, and only for a champion who can use that item. Owned attack-damage items do not turn a mage into a marksman, and owned ability-power items do not turn a marksman into a mage. Quest rewards such as The Golden Spatula are not shop buys.

Augment ids are not in the live game API or the game log. During the match the overlay reads the League window with Windows OCR. A word becomes an augment only when it matches a name already in Community Dragon's Mayhem list, so a misread is dropped instead of invented. Names next to his champion are his, names next to an enemy champion are theirs, and a row of cards with no champion is the selection still on screen. After the cards leave, those names stay for the rest of the match. If no cards are on screen yet, the panel says the augments are not visible yet. The end-of-game screen and the saved match still supply `playerAugment` numbers for every player, and those ids are matched to the same list. A description that says grievous skips a second grievous item. Healing, shields, armor, and magic resist in an enemy augment move the same buys as those words on an item.

Champion select on the bridge ignores lanes. It wants poke, a frontline, and sustain for the team you can see. The bench is part of the lock list. Your current champion is kept when it scores best. A better bench champion is a swap. A reroll is suggested only when enemies are visible, rerolls remain, and the champion you have scores poorly with nothing better on the bench.

## What this is not

- Not a win rate, pick rate, or pro-build database.
- Not a full rune page or skill order.
- Not an automatic shop. It only displays the next buy.
- Summoner's Rift and the bridge use different item lists. Prices in the live shop can differ from Data Dragon.
