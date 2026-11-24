"""Screen reading keeps real augment names and drops everything else."""

from __future__ import annotations

import unittest

from league_overlay.augments import AugmentBook
from league_overlay.lcu import LcuResult
from league_overlay.live import LiveResult
from league_overlay.screen_augments import (
    AugmentMemory,
    OcrWord,
    Person,
    ScreenHit,
    read_augments,
)
from league_overlay.view import build_view
from tests.test_mayhem import bridge_catalog, game

NAMES = (
    "Can't Touch This",
    "Leg Day",
    "BEES!!!",
    "Pinball",
    "Fruitify",
    "Scopier Weapons",
    "Shadow Runner",
    "Bread and Cheese",
    "Jeweled Bracelet",
    "Ravenous Bind",
    "Deft",
    "Eureka",
)


def word(text: str, x: int, y: int, w: int = 80, h: int = 30) -> OcrWord:
    return OcrWord(text, x, y, w, h)


def line(text: str, x: int, y: int, h: int = 30) -> list[OcrWord]:
    parts = text.split()
    words = []
    cursor = x
    for part in parts:
        width = max(20, 16 * len(part))
        words.append(word(part, cursor, y, width, h))
        cursor += width + 8
    return words


VI = Person("Vi", enemy=False, you=True)
SWAIN = Person("Swain", enemy=False, you=False)
CORKI = Person("Corki", enemy=True, you=False)
RENGAR = Person("Rengar", enemy=True, you=False)


class ReadTests(unittest.TestCase):
    def test_scoreboard_row_assigns_his_augment_and_the_enemy(self) -> None:
        words = [
            word("Vi", 80, 110, 40),
            *line("Can't Touch This", 360, 114),
            word("Corki", 760, 114, 90),
            *line("Scopier Weapons", 1060, 114),
            word("Swain", 80, 199, 100),
            *line("Leg Day", 360, 199),
            word("Rengar", 760, 199, 120),
            *line("Shadow Runner", 1060, 199),
        ]
        hit = read_augments(words, NAMES, (VI, SWAIN, CORKI, RENGAR), width=1400, height=800)
        self.assertEqual(hit.yours, ("Can't Touch This",))
        self.assertEqual(hit.enemies, ("Scopier Weapons", "Shadow Runner"))
        self.assertNotIn("Leg Day", hit.yours)

    def test_summoner_name_keeps_his_row_when_the_champion_is_missed(self) -> None:
        you = Person("WhyCantIChangeIt", enemy=False, you=True)
        words = [
            *line("WhyCantIChangeIt", 80, 114),
            *line("Can't Touch This", 500, 114),
            word("Corki", 760, 114, 90),
            *line("Scopier Weapons", 1060, 114),
        ]
        hit = read_augments(words, NAMES, (you, CORKI), width=1400, height=800)
        self.assertEqual(hit.yours, ("Can't Touch This",))
        self.assertEqual(hit.enemies, ("Scopier Weapons",))

    def test_a_missed_enemy_does_not_donate_their_augment(self) -> None:
        words = [
            word("Vi", 80, 114, 40),
            *line("Can't Touch This", 360, 114),
            *line("Scopier Weapons", 1060, 114),
        ]
        hit = read_augments(words, NAMES, (VI, CORKI), width=1400, height=800)
        self.assertEqual(hit.yours, ("Can't Touch This",))
        self.assertNotIn("Scopier Weapons", hit.yours)
        self.assertNotIn("Scopier Weapons", hit.enemies)

    def test_a_missed_champion_is_not_given_to_the_enemy_on_that_row(self) -> None:
        # Windows OCR dropped "Vi" on a drawn scoreboard. The augment stays unassigned.
        words = [
            *line("Can't Touch This", 362, 119),
            word("Corki", 762, 119, 93),
            *line("Scopier Weapons", 1062, 119),
        ]
        hit = read_augments(words, NAMES, (VI, CORKI), width=1400, height=800)
        self.assertEqual(hit.enemies, ("Scopier Weapons",))
        self.assertNotIn("Can't Touch This", hit.enemies)
        self.assertNotIn("Can't Touch This", hit.yours)

    def test_chat_and_unknown_words_are_not_augments(self) -> None:
        words = line("Buwuy has slain Yunara with Can't Touch This", 40, 80)
        words.extend(line("a totally made up prismatic", 40, 200))
        words.extend([word("Deft", 40, 300, 60), word("hands", 120, 300, 80)])
        hit = read_augments(words, NAMES, (VI,), width=1400, height=800)
        self.assertEqual(hit, ScreenHit())

    def test_selection_cards_are_not_treated_as_equipped(self) -> None:
        words = [
            *line("Eureka", 160, 280),
            *line("Reroll", 160, 340),
            *line("Jeweled Bracelet", 620, 280),
            *line("Ravenous Bind", 1040, 280),
        ]
        hit = read_augments(words, NAMES, (VI, CORKI), width=1400, height=800)
        self.assertEqual(hit.yours, ())
        self.assertEqual(hit.enemies, ())
        self.assertEqual(hit.cards, ("Eureka", "Jeweled Bracelet", "Ravenous Bind"))

    def test_bottom_left_names_are_his(self) -> None:
        words = line("Pinball", 40, 700)
        hit = read_augments(words, NAMES, (VI,), width=1400, height=800)
        self.assertEqual(hit.yours, ("Pinball",))
        self.assertEqual(hit.cards, ())


class MemoryTests(unittest.TestCase):
    def test_names_stay_until_the_next_game(self) -> None:
        memory = AugmentMemory()
        key = ("Vi", ("Corki", "Vi"))
        shown = memory.merge(key, 100, ScreenHit(yours=("Leg Day",), enemies=("Pinball",)))
        self.assertEqual(shown.yours, ("Leg Day",))
        shown = memory.merge(key, 130, ScreenHit(cards=("Eureka",)))
        self.assertEqual(shown.yours, ("Leg Day",))
        self.assertEqual(shown.enemies, ("Pinball",))
        self.assertEqual(shown.cards, ("Eureka",))
        shown = memory.merge(key, 20, ScreenHit())
        self.assertEqual(shown.yours, ())
        self.assertEqual(shown.cards, ())


class ViewTests(unittest.TestCase):
    def test_overlay_says_when_cards_are_missing_and_shows_them_when_read(self) -> None:
        catalog = bridge_catalog()
        payload = game("KIWI")
        empty, _interval = build_view(LiveResult("ok", payload), LcuResult.down(), catalog)
        self.assertIn("not visible yet", empty.ingame.detail_line.lower())
        book = AugmentBook.from_pairs({1: ("Can't Touch This", "You take less damage.")})
        seen = ScreenHit(yours=("Can't Touch This",), enemies=("Not A Real Augment",))
        shown, _interval = build_view(LiveResult("ok", payload), LcuResult.down(), catalog, book, seen)
        self.assertIn("Your augments: Can't Touch This", shown.ingame.detail_line)
        self.assertNotIn("Not A Real Augment", shown.ingame.detail_line)
        cards, _interval = build_view(
            LiveResult("ok", payload),
            LcuResult.down(),
            catalog,
            book,
            ScreenHit(cards=("Can't Touch This",)),
        )
        self.assertIn("Augment cards on screen: Can't Touch This", cards.ingame.detail_line)
        self.assertNotIn("not visible yet", cards.ingame.detail_line.lower())


if __name__ == "__main__":
    unittest.main()
