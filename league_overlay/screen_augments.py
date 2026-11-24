"""Read Mayhem augment names off the League window.

The live client and the game log do not include the picks. When the cards
or the scoreboard are on screen, Windows OCR reads the words and this module
keeps a name only when it is already in the augment list. Nothing is invented.
"""

from __future__ import annotations

import ctypes
import subprocess
import threading
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from league_overlay.augments import AugmentBook, norm_token
from league_overlay.live import match_player
from league_overlay.modeinfo import detect_mode
from league_overlay.paths import CACHE

LEAGUE_TITLE = "League of Legends (TM) Client"
OVERLAY_TITLE = "League Overlay"
_MAX_WIDTH = 2000
_CHAT = (
    "has slain",
    "was slain",
    "purchased",
    "shut down",
    "double kill",
    "quadra kill",
    "penta kill",
    "killing spree",
    "is on a",
)
_IGNORE = {"reroll", "silver", "gold", "prismatic", "choose", "augment", "augments", "hacked"}
_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($op, $type) {
    $method = $asTaskGeneric.MakeGenericMethod($type)
    $task = $method.Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    return $task.Result
}
function Box($word) {
    $r = $word.BoundingRect
    if ($r -is [System.Array]) { return @([int]$r[0], [int]$r[1], [int]$r[2], [int]$r[3]) }
    return @([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height)
}
$path = $args[0]
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$lang = [Windows.Globalization.Language]::new('en-US')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($null -eq $engine) { return }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) {
    foreach ($word in @($line.Words)) {
        $box = Box $word
        $text = ([string]$word.Text) -replace "[`t`r`n]", ' '
        Write-Output ("{0}`t{1}`t{2}`t{3}`t{4}" -f $box[0], $box[1], $box[2], $box[3], $text)
    }
}
"""


@dataclass(frozen=True)
class OcrWord:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass(frozen=True)
class Person:
    label: str
    enemy: bool
    you: bool


@dataclass(frozen=True)
class ScreenHit:
    yours: tuple[str, ...] = ()
    enemies: tuple[str, ...] = ()
    cards: tuple[str, ...] = ()

    @property
    def visible(self) -> bool:
        return bool(self.yours or self.enemies or self.cards)


@dataclass
class AugmentMemory:
    """Keep names after the cards leave the screen, until the next game."""

    key: tuple = ()
    clock: float = 0.0
    yours: list[str] = field(default_factory=list)
    enemies: list[str] = field(default_factory=list)

    def merge(self, key: tuple, clock: float, hit: ScreenHit) -> ScreenHit:
        if key != self.key or (self.clock > 45 and clock + 20 < self.clock):
            self.key = key
            self.clock = clock
            self.yours = []
            self.enemies = []
        self.clock = clock
        for name in hit.yours:
            if name not in self.yours:
                self.yours.append(name)
        for name in hit.enemies:
            if name not in self.enemies and name not in self.yours:
                self.enemies.append(name)
        cards = tuple(name for name in hit.cards if name not in self.yours and name not in self.enemies)
        return ScreenHit(tuple(self.yours), tuple(self.enemies), cards)

    def clear(self) -> None:
        self.key = ()
        self.clock = 0.0
        self.yours = []
        self.enemies = []


def _forms(label: str) -> tuple[tuple[str, ...], ...]:
    """Word forms OCR can return, including a name whose apostrophe was dropped or split."""
    found: list[tuple[str, ...]] = []
    for source in (label, label.replace("'", " ").replace("\u2019", " ").replace("\u2018", " ")):
        parts = tuple(token for token in (norm_token(part) for part in source.split()) if token)
        if parts and parts not in found:
            found.append(parts)
    compact = norm_token(label)
    if compact and (compact,) not in found:
        found.append((compact,))
    return tuple(found)


def _index_people(people: tuple[Person, ...] | list[Person]) -> dict[tuple[str, ...], Person]:
    index: dict[tuple[str, ...], Person] = {}
    for person in people:
        for form in _forms(person.label):
            index.setdefault(form, person)
    return index


def _index_augments(names: tuple[str, ...] | list[str]) -> list[tuple[tuple[str, ...], str, bool]]:
    rows: list[tuple[tuple[str, ...], str, bool]] = []
    seen: set[tuple[str, ...]] = set()
    for name in names:
        label = str(name).strip()
        if not label:
            continue
        for form in _forms(label):
            if form in seen:
                continue
            seen.add(form)
            short = len(form) == 1 and len(form[0]) < 6
            rows.append((form, label, short))
    rows.sort(key=lambda row: len(row[0]), reverse=True)
    return rows


def _rows(words: list[OcrWord]) -> list[list[OcrWord]]:
    ordered = sorted(words, key=lambda word: (word.cy, word.x))
    rows: list[list[OcrWord]] = []
    for word in ordered:
        if not rows or abs(word.cy - rows[-1][0].cy) > max(18, int(rows[-1][0].h * 0.8)):
            rows.append([word])
        else:
            rows[-1].append(word)
    for row in rows:
        row.sort(key=lambda word: word.x)
    return rows


def _chat(row: list[OcrWord]) -> bool:
    text = " ".join(word.text for word in row).casefold()
    return any(phrase in text for phrase in _CHAT)


def _person_spans(tokens: list[str], people: dict[tuple[str, ...], Person]) -> list[tuple[int, int, Person]]:
    spans: list[tuple[int, int, Person]] = []
    index = 0
    while index < len(tokens):
        found = None
        for length in range(min(3, len(tokens) - index), 0, -1):
            person = people.get(tuple(tokens[index : index + length]))
            if person is not None:
                found = (index, index + length, person)
                break
        if found is None:
            index += 1
            continue
        spans.append(found)
        index = found[1]
    return spans


def _phrase_at(
    tokens: list[str],
    start: int,
    augments: list[tuple[tuple[str, ...], str, bool]],
) -> tuple[int, str, bool] | None:
    for form, label, short in augments:
        size = len(form)
        if tokens[start : start + size] == list(form):
            return size, label, short
    return None


def _segment_augments(
    tokens: list[str],
    augments: list[tuple[tuple[str, ...], str, bool]],
) -> list[str]:
    """Augment names in one person's slice of a scoreboard row."""
    found: list[tuple[int, int, str, bool]] = []
    index = 0
    while index < len(tokens):
        hit = _phrase_at(tokens, index, augments)
        if hit is None:
            index += 1
            continue
        size, label, short = hit
        found.append((index, index + size, label, short))
        index += size
    if not found:
        return []
    used = {slot for start, end, _label, _short in found for slot in range(start, end)}
    extras = [
        token
        for slot, token in enumerate(tokens)
        if slot not in used and token not in _IGNORE and not token.isdigit()
    ]
    names: list[str] = []
    for _start, _end, label, short in found:
        if short and extras:
            continue
        if label not in names:
            names.append(label)
    return names


def _open_row_augments(
    tokens: list[str],
    augments: list[tuple[tuple[str, ...], str, bool]],
) -> list[str]:
    """A card row: the words are the augment names, not a sentence."""
    content = [token for token in tokens if token and token not in _IGNORE and not token.isdigit()]
    if not content:
        return []
    found: list[tuple[int, int, str]] = []
    index = 0
    while index < len(content):
        hit = _phrase_at(content, index, augments)
        if hit is None:
            index += 1
            continue
        size, label, short = hit
        if short and content != list(content[index : index + size]):
            index += 1
            continue
        found.append((index, index + size, label))
        index += size
    covered = sum(end - start for start, end, _label in found)
    if not found or covered < max(1, int(0.6 * len(content))):
        return []
    names: list[str] = []
    for _start, _end, label in found:
        if label not in names:
            names.append(label)
    return names


def read_augments(
    words: list[OcrWord],
    augment_names: tuple[str, ...] | list[str],
    people: tuple[Person, ...] | list[Person],
    *,
    width: int,
    height: int,
) -> ScreenHit:
    """Turn OCR words into your augments, enemy augments, or the cards on screen."""
    augments = _index_augments(augment_names)
    people_index = _index_people(people)
    if not augments or not words:
        return ScreenHit()
    yours: list[str] = []
    enemies: list[str] = []
    cards: list[str] = []

    def add(bucket: list[str], names: list[str], blocked: tuple[str, ...] = ()) -> None:
        for name in names:
            if name not in bucket and name not in blocked:
                bucket.append(name)

    for row in _rows(words):
        if _chat(row):
            continue
        tokens = [norm_token(word.text) for word in row]
        spans = _person_spans(tokens, people_index)
        if not spans:
            names = _open_row_augments(tokens, augments)
            if not names:
                continue
            top = min(word.y for word in row)
            if height > 0 and top > height * 0.72 and all(word.x < width * 0.45 for word in row):
                add(yours, names)
            else:
                add(cards, names, tuple(yours) + tuple(enemies))
            continue
        if spans[0][0] > 0:
            # A name to the left of every champion is not that champion's augment.
            pass
        for position, (start, end, person) in enumerate(spans):
            nxt = spans[position + 1][0] if position + 1 < len(spans) else len(tokens)
            # The other team's column is the other half of the window. A missed
            # name must not pull that column's augment onto this player.
            anchor = row[start].x
            body = [
                token
                for word, token in zip(row[end:nxt], tokens[end:nxt])
                if width <= 0 or (anchor < width / 2) == (word.x < width / 2)
            ]
            names = _segment_augments(body, augments)
            if person.you:
                add(yours, names)
            elif person.enemy:
                add(enemies, names)
    return ScreenHit(tuple(yours), tuple(enemies), tuple(cards))


def _script_path() -> Path:
    path = CACHE / "screen-ocr.ps1"
    if not path.is_file() or path.read_text(encoding="utf-8") != _PS.strip() + "\n":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_PS.strip() + "\n", encoding="utf-8")
    return path


def ocr_image(path: Path) -> list[OcrWord]:
    """Read one image with the Windows OCR engine. Returns no words if it cannot."""
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_script_path()),
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    words: list[OcrWord] = []
    for line in (completed.stdout or "").splitlines():
        parts = line.split("\t", 4)
        if len(parts) != 5:
            continue
        try:
            x, y, w, h = (int(part) for part in parts[:4])
        except ValueError:
            continue
        text = parts[4].strip()
        if text:
            words.append(OcrWord(text, x, y, max(w, 1), max(h, 1)))
    return words


def _enum_hwnd(title: str) -> int:
    user32 = ctypes.windll.user32
    found = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):  # type: ignore[no-untyped-def]
        nonlocal found
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if buffer.value == title and found == 0:
            found = int(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def _rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not hwnd:
        return None
    box = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(box)):
        return None
    width = box.right - box.left
    height = box.bottom - box.top
    if width < 200 or height < 200:
        return None
    return box.left, box.top, width, height


def _write_bmp(path: Path, width: int, height: int, bgra: bytes) -> None:
    row = width * 4
    header = 14 + 40
    size = header + row * height
    data = bytearray(size)
    data[0:2] = b"BM"
    data[2:6] = size.to_bytes(4, "little")
    data[10:14] = header.to_bytes(4, "little")
    data[14:18] = (40).to_bytes(4, "little")
    data[18:22] = width.to_bytes(4, "little", signed=True)
    data[22:26] = height.to_bytes(4, "little", signed=True)
    data[26:28] = (1).to_bytes(2, "little")
    data[28:30] = (32).to_bytes(2, "little")
    # Bottom-up rows so the file is a normal BMP.
    for y in range(height):
        start = (height - 1 - y) * row
        data[header + y * row : header + (y + 1) * row] = bgra[start : start + row]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _fill(bgra: bytearray, width: int, height: int, left: int, top: int, right: int, bottom: int) -> None:
    left = max(0, min(width, left))
    right = max(0, min(width, right))
    top = max(0, min(height, top))
    bottom = max(0, min(height, bottom))
    for y in range(top, bottom):
        start = (y * width + left) * 4
        end = (y * width + right) * 4
        bgra[start:end] = b"\x00" * (end - start)


def capture_league() -> tuple[list[OcrWord], int, int]:
    """Capture the League window, hide our own overlay, and OCR it."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    league = _rect(_enum_hwnd(LEAGUE_TITLE))
    if league is None:
        return [], 0, 0
    left, top, width, height = league
    dest_w = min(_MAX_WIDTH, width)
    dest_h = max(1, int(height * dest_w / width))
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    screen = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, dest_w, dest_h)
    old = gdi32.SelectObject(memory, bitmap)
    gdi32.SetStretchBltMode(memory, 4)
    gdi32.StretchBlt(memory, 0, 0, dest_w, dest_h, screen, left, top, width, height, 0x00CC0020)
    class Header(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    header = Header()
    header.biSize = ctypes.sizeof(Header)
    header.biWidth = dest_w
    header.biHeight = -dest_h
    header.biPlanes = 1
    header.biBitCount = 32
    pixels = ctypes.create_string_buffer(dest_w * dest_h * 4)
    gdi32.GetDIBits(memory, bitmap, 0, dest_h, pixels, ctypes.byref(header), 0)
    gdi32.SelectObject(memory, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(0, screen)
    raw = bytearray(pixels)
    overlay = _rect(_enum_hwnd(OVERLAY_TITLE))
    if overlay is not None:
        ox, oy, ow, oh = overlay
        scale_x = dest_w / width
        scale_y = dest_h / height
        _fill(
            raw,
            dest_w,
            dest_h,
            int((ox - left) * scale_x),
            int((oy - top) * scale_y),
            int((ox + ow - left) * scale_x),
            int((oy + oh - top) * scale_y),
        )
    image = CACHE / "screen.bmp"
    _write_bmp(image, dest_w, dest_h, bytes(raw))
    return ocr_image(image), dest_w, dest_h


def _handle(name: object) -> str:
    text = str(name or "").split("#", 1)[0].strip()
    return text


def roster_from_live(data: dict | None, queue_id: int | None) -> tuple[bool, tuple, float, tuple[Person, ...]]:
    """Whether to read the screen, plus the game key, clock, and the ten players."""
    if not isinstance(data, dict):
        return False, (), 0.0, ()
    game_data = data.get("gameData") if isinstance(data.get("gameData"), dict) else {}
    try:
        clock = float(game_data.get("gameTime") or 0)
    except (TypeError, ValueError):
        clock = 0.0
    info = detect_mode(
        game_mode=str(game_data.get("gameMode") or ""),
        map_name=str(game_data.get("mapName") or ""),
        map_number=game_data.get("mapNumber"),
        queue_id=queue_id,
    )
    enabled = info.kind in {"mayhem", "aram-unconfirmed"}
    active = data.get("activePlayer") if isinstance(data.get("activePlayer"), dict) else {}
    players = data.get("allPlayers") if isinstance(data.get("allPlayers"), list) else []
    me = match_player(active, players)
    people: list[Person] = []
    champions: list[str] = []
    you = ""
    for player in players:
        if not isinstance(player, dict):
            continue
        champion = str(player.get("championName") or "").strip()
        summoner = _handle(player.get("summonerName") or player.get("riotId") or "")
        enemy = bool(me) and player.get("team") != me.get("team")
        local = player is me
        if champion:
            champions.append(champion)
            people.append(Person(champion, enemy and not local, local))
        if summoner and summoner.casefold() != champion.casefold():
            people.append(Person(summoner, enemy and not local, local))
        if local and champion:
            you = champion
    key = (you, tuple(sorted(champions)), info.kind)
    return enabled, key, clock, tuple(people)


class ScreenWatcher:
    """OCR the League window on a side thread so the shop poll stays quick."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._enabled = False
        self._names: tuple[str, ...] = ()
        self._people: tuple[Person, ...] = ()
        self._key: tuple = ()
        self._clock = 0.0
        self._memory = AugmentMemory()
        self._shown = ScreenHit()
        self._thread = threading.Thread(target=self._loop, name="screen-augments", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def update(self, data: dict | None, queue_id: int | None, book: AugmentBook | None) -> None:
        enabled, key, clock, people = roster_from_live(data, queue_id)
        names = book.names() if book is not None and book.ready else ()
        with self._lock:
            self._enabled = enabled and bool(names)
            self._names = names
            self._people = people
            self._key = key
            self._clock = clock
            if not enabled:
                self._memory.clear()
                self._shown = ScreenHit()
        self._wake.set()

    def snapshot(self) -> ScreenHit:
        with self._lock:
            return self._shown

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(2.0)
            self._wake.clear()
            if self._stop.is_set():
                return
            with self._lock:
                enabled = self._enabled
                names = self._names
                people = self._people
                key = self._key
                clock = self._clock
            if not enabled or not names:
                continue
            try:
                words, width, height = capture_league()
                hit = read_augments(words, names, people, width=width, height=height)
            except Exception:
                continue
            with self._lock:
                if key != self._key:
                    continue
                self._shown = self._memory.merge(key, clock, hit)
