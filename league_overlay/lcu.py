"""League client (LCU) via the local lockfile. The password never leaves this PC."""

from __future__ import annotations

import base64
import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from league_overlay.modeinfo import queue_id_from_gameflow
from league_overlay.net import local_json

NAME_HINTS = ("leagueclientux.exe", "leagueclient.exe")
COMMON_LOCKFILES = (
    Path(r"C:\Riot Games\League of Legends\lockfile"),
    Path(r"C:\Riot Games\League of Legends\LeagueClient\lockfile"),
)


@dataclass
class Lockfile:
    process: str
    pid: int
    port: int
    password: str
    protocol: str

    def __repr__(self) -> str:
        return f"Lockfile(port={self.port}, protocol={self.protocol})"

    def url(self, path: str) -> str:
        return f"{self.protocol}://127.0.0.1:{self.port}{path}"

    def headers(self) -> dict[str, str]:
        token = base64.b64encode(f"riot:{self.password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}", "Accept": "application/json"}


@dataclass
class ChampSelect:
    allies: list[int] = field(default_factory=list)
    enemies: list[int] = field(default_factory=list)
    bans: list[int] = field(default_factory=list)
    pickable: list[int] | None = None
    position: str = ""
    locked_id: int = 0
    local_champion_id: int = 0
    rerolls_remaining: int | None = None


@dataclass(frozen=True)
class PlayerBoard:
    champion_id: int
    champion_name: str
    team_id: int
    local: bool
    items: tuple[int, ...]
    augments: tuple[int, ...]


@dataclass(frozen=True)
class MatchBoard:
    game_id: int
    queue_id: int | None
    players: tuple[PlayerBoard, ...]

    def local_player(self) -> PlayerBoard | None:
        for player in self.players:
            if player.local:
                return player
        return None

    def enemy_players(self) -> tuple[PlayerBoard, ...]:
        local = self.local_player()
        found: list[PlayerBoard] = []
        for player in self.players:
            if player.local:
                continue
            if local is not None and local.team_id and player.team_id and player.team_id == local.team_id:
                continue
            found.append(player)
        return tuple(found)


@dataclass
class LcuResult:
    status: str
    select: ChampSelect | None = None
    detail: str = ""
    queue_id: int | None = None
    board: MatchBoard | None = None

    @staticmethod
    def down() -> LcuResult:
        return LcuResult("down")


_SKIP_ITEMS = {3330, 3340, 3363, 3364, 3513}
_board_cache: dict[str, object] = {"game_id": 0, "at": 0.0, "board": None}


def _keep_item(item_id: int) -> bool:
    return 0 < item_id < 200_000 and item_id not in _SKIP_ITEMS


def _augments_from_stats(stats: dict) -> tuple[int, ...]:
    found: list[int] = []
    for index in range(1, 7):
        raw = stats.get(f"playerAugment{index}")
        if raw is None:
            raw = stats.get(f"PLAYER_AUGMENT_{index}")
        value = _number(raw)
        if value > 0:
            found.append(value)
    return tuple(found)


def _items_from_player(player: dict, stats: dict) -> tuple[int, ...]:
    found: list[int] = []
    raw = player.get("items")
    if isinstance(raw, list) and raw:
        for entry in raw:
            if isinstance(entry, dict):
                item_id = _number(entry.get("itemID") or entry.get("id"))
            else:
                item_id = _number(entry)
            if _keep_item(item_id):
                found.append(item_id)
        return tuple(found)
    for index in range(7):
        raw_id = stats.get(f"item{index}")
        if raw_id is None:
            raw_id = stats.get(f"ITEM_{index}")
        item_id = _number(raw_id)
        if _keep_item(item_id):
            found.append(item_id)
    return tuple(found)


def parse_eog(body: dict) -> MatchBoard | None:
    """End-of-game screen. This is where Mayhem augment ids show up for every player."""
    if not isinstance(body, dict) or not isinstance(body.get("teams"), list):
        return None
    players: list[PlayerBoard] = []
    for team in body["teams"]:
        if not isinstance(team, dict):
            continue
        team_id = _number(team.get("teamId"))
        for player in team.get("players") or []:
            if not isinstance(player, dict):
                continue
            stats = player.get("stats") if isinstance(player.get("stats"), dict) else {}
            players.append(
                PlayerBoard(
                    champion_id=_number(player.get("championId")),
                    champion_name=str(player.get("championName") or ""),
                    team_id=team_id,
                    local=bool(player.get("isLocalPlayer")),
                    items=_items_from_player(player, stats),
                    augments=_augments_from_stats(stats),
                )
            )
    if not players:
        return None
    queue = _number(body.get("queueId")) or None
    return MatchBoard(_number(body.get("gameId")), queue, tuple(players))


def parse_match(body: dict, local_puuid: str = "") -> MatchBoard | None:
    """Full match history game. Same augment ids, after the client has saved the match."""
    if not isinstance(body, dict) or not isinstance(body.get("participants"), list):
        return None
    identities: dict[int, str] = {}
    for ident in body.get("participantIdentities") or []:
        if not isinstance(ident, dict):
            continue
        person = ident.get("player") if isinstance(ident.get("player"), dict) else {}
        identities[_number(ident.get("participantId"))] = str(person.get("puuid") or "")
    players: list[PlayerBoard] = []
    for part in body["participants"]:
        if not isinstance(part, dict):
            continue
        stats = part.get("stats") if isinstance(part.get("stats"), dict) else {}
        puuid = identities.get(_number(part.get("participantId")), "")
        players.append(
            PlayerBoard(
                champion_id=_number(part.get("championId")),
                champion_name="",
                team_id=_number(part.get("teamId")),
                local=bool(local_puuid) and puuid == local_puuid,
                items=_items_from_player(part, stats),
                augments=_augments_from_stats(stats),
            )
        )
    if not players:
        return None
    queue = _number(body.get("queueId")) or None
    return MatchBoard(_number(body.get("gameId")), queue, tuple(players))


def _number(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _current_puuid(lock: Lockfile) -> str:
    code, body, error = local_json(
        lock.url("/lol-summoner/v1/current-summoner"),
        headers=lock.headers(),
        timeout=1.5,
    )
    if error or code != 200 or not isinstance(body, dict):
        return ""
    return str(body.get("puuid") or "")


def load_board(lock: Lockfile, session: dict | None) -> MatchBoard | None:
    """Read augments for the current game id. Retries slowly until the client has saved them."""
    if not isinstance(session, dict):
        return None
    game_data = session.get("gameData") if isinstance(session.get("gameData"), dict) else {}
    game_id = _number(game_data.get("gameId"))
    if game_id <= 0:
        return None
    now = time.monotonic()
    cached_id = _board_cache.get("game_id")
    cached_board = _board_cache.get("board")
    age = now - float(_board_cache.get("at") or 0)
    if cached_id == game_id and isinstance(cached_board, MatchBoard) and age < 3:
        return cached_board
    if cached_id == game_id and cached_board is None and age < 2:
        return None
    board = _read_board(lock, game_id)
    queue = queue_id_from_gameflow(session)
    if board is not None and board.queue_id is None and queue:
        board = MatchBoard(board.game_id, queue, board.players)
    _board_cache["game_id"] = game_id
    _board_cache["at"] = now
    _board_cache["board"] = board
    return board


def _read_board(lock: Lockfile, game_id: int) -> MatchBoard | None:
    code, body, error = local_json(
        lock.url("/lol-end-of-game/v1/eog-stats-block"),
        headers=lock.headers(),
        timeout=1.5,
    )
    if not error and code == 200 and isinstance(body, dict) and _number(body.get("gameId")) == game_id:
        board = parse_eog(body)
        if board is not None and any(player.augments for player in board.players):
            return board
    code, body, error = local_json(
        lock.url(f"/lol-match-history/v1/games/{game_id}"),
        headers=lock.headers(),
        timeout=1.5,
    )
    if error or code != 200 or not isinstance(body, dict):
        return None
    return parse_match(body, _current_puuid(lock))


def parse_lockfile(text: str) -> Lockfile:
    line = ""
    for candidate in text.splitlines():
        if candidate.strip():
            line = candidate.strip()
            break
    parts = line.split(":")
    if len(parts) < 5:
        raise ValueError("lockfile")
    process, pid, port, *middle, protocol = parts
    password = ":".join(middle)
    if not pid.isdigit() or not port.isdigit() or not password:
        raise ValueError("lockfile")
    if protocol not in {"https", "http"}:
        raise ValueError("lockfile")
    return Lockfile(process, int(pid), int(port), password, protocol)


def _read_shared(path: Path) -> str:
    kernel32 = ctypes.windll.kernel32
    generic_read = 0x80000000
    share = 0x1 | 0x2 | 0x4
    handle = kernel32.CreateFileW(str(path), generic_read, share, None, 3, 0x80, None)
    invalid = ctypes.c_void_p(-1).value
    if not handle or handle == invalid:
        raise OSError("lockfile busy")
    try:
        chunks: list[bytes] = []
        while True:
            buffer = ctypes.create_string_buffer(4096)
            read = wintypes.DWORD()
            ok = kernel32.ReadFile(handle, buffer, 4096, ctypes.byref(read), None)
            if not ok or read.value == 0:
                break
            chunks.append(buffer.raw[: read.value])
    finally:
        kernel32.CloseHandle(handle)
    return b"".join(chunks).decode("utf-8", errors="replace")


def read_lockfile_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return _read_shared(path)


def _process_dirs() -> list[Path]:
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return []
    kernel32 = ctypes.windll.kernel32
    snapshot_flags = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(snapshot_flags, 0)
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid:
        return []
    found: list[Path] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            name = entry.szExeFile.casefold()
            if name in NAME_HINTS:
                process = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                if process:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(32768)
                        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                            found.append(Path(buffer.value).resolve().parent)
                    finally:
                        kernel32.CloseHandle(process)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return found


_cached_path: Path | None = None
_cached_until = 0.0


def find_lockfile() -> Path | None:
    """Locate League's lockfile. Returns None when the client is not running."""
    global _cached_path, _cached_until
    now = time.monotonic()
    if _cached_path is not None and now < _cached_until and _cached_path.is_file():
        return _cached_path
    found: Path | None = None
    try:
        for path in COMMON_LOCKFILES:
            if path.is_file():
                found = path
                break
        if found is None:
            for folder in _process_dirs():
                candidate = folder / "lockfile"
                if candidate.is_file():
                    found = candidate
                    break
    except Exception:
        found = None
    _cached_path = found
    _cached_until = now + (5 if found else 2)
    return found


def _positive_ids(values: object) -> list[int]:
    found: list[int] = []
    if not isinstance(values, list):
        return found
    for value in values:
        try:
            champion_id = int(value)
        except (TypeError, ValueError):
            continue
        if champion_id > 0:
            found.append(champion_id)
    return found


def _bench_ids(session: dict) -> list[int]:
    found: list[int] = []
    for entry in session.get("benchChampions") or []:
        if isinstance(entry, dict):
            found.extend(_positive_ids([entry.get("championId")]))
        else:
            found.extend(_positive_ids([entry]))
    return found


def parse_session(session: dict, pickable: list[int] | None) -> ChampSelect:
    local_cell = session.get("localPlayerCellId")
    try:
        local_cell_id = int(local_cell)
    except (TypeError, ValueError):
        local_cell_id = -1
    allies: list[int] = []
    position = ""
    local_champion = 0
    for member in session.get("myTeam") or []:
        if not isinstance(member, dict):
            continue
        try:
            cell = int(member.get("cellId"))
        except (TypeError, ValueError):
            cell = -2
        champion_id = 0
        try:
            champion_id = int(member.get("championId") or 0)
        except (TypeError, ValueError):
            champion_id = 0
        if cell == local_cell_id:
            position = str(member.get("assignedPosition") or "")
            local_champion = champion_id if champion_id > 0 else 0
            continue
        if champion_id > 0:
            allies.append(champion_id)
    enemies: list[int] = []
    for member in session.get("theirTeam") or []:
        if not isinstance(member, dict):
            continue
        try:
            champion_id = int(member.get("championId") or 0)
        except (TypeError, ValueError):
            champion_id = 0
        if champion_id > 0:
            enemies.append(champion_id)
    bans = set(_positive_ids((session.get("bans") or {}).get("myTeamBans") if isinstance(session.get("bans"), dict) else []))
    their_bans = (session.get("bans") or {}).get("theirTeamBans") if isinstance(session.get("bans"), dict) else []
    bans.update(_positive_ids(their_bans))
    locked = 0
    for phase in session.get("actions") or []:
        if not isinstance(phase, list):
            continue
        for action in phase:
            if not isinstance(action, dict):
                continue
            try:
                actor = int(action.get("actorCellId"))
                champion_id = int(action.get("championId") or 0)
            except (TypeError, ValueError):
                continue
            if action.get("type") == "ban" and action.get("completed") and champion_id > 0:
                bans.add(champion_id)
            if (
                actor == local_cell_id
                and action.get("type") == "pick"
                and action.get("completed")
                and champion_id > 0
            ):
                locked = champion_id
    bench = _bench_ids(session)
    resolved = pickable
    if bench:
        ids = set(bench)
        if local_champion:
            ids.add(local_champion)
        resolved = sorted(ids)
    rerolls: int | None = None
    if "rerollsRemaining" in session:
        try:
            rerolls = max(0, int(session.get("rerollsRemaining") or 0))
        except (TypeError, ValueError):
            rerolls = None
    return ChampSelect(
        allies=allies,
        enemies=enemies,
        bans=sorted(bans),
        pickable=resolved,
        position=position,
        locked_id=locked,
        local_champion_id=local_champion or locked,
        rerolls_remaining=rerolls,
    )


def _fetch_pickable(lock: Lockfile) -> list[int] | None:
    code, body, error = local_json(
        lock.url("/lol-champ-select/v1/pickable-champion-ids"),
        headers=lock.headers(),
    )
    if error or code != 200 or not isinstance(body, list):
        return None
    return _positive_ids(body)


def _gameflow(lock: Lockfile) -> dict | None:
    code, body, error = local_json(lock.url("/lol-gameflow/v1/session"), headers=lock.headers())
    if error or code != 200 or not isinstance(body, dict):
        return None
    return body


def fetch_lcu() -> LcuResult:
    try:
        path = find_lockfile()
    except Exception:
        return LcuResult.down()
    if path is None:
        return LcuResult.down()
    try:
        lock = parse_lockfile(read_lockfile_text(path))
    except Exception:
        return LcuResult("error", detail="Could not read the League lockfile.")
    session = _gameflow(lock)
    queue_id = queue_id_from_gameflow(session) if session else None
    board = None
    try:
        board = load_board(lock, session)
    except Exception:
        board = None
    if queue_id is None and board is not None and board.queue_id:
        queue_id = board.queue_id
    code, body, error = local_json(lock.url("/lol-champ-select/v1/session"), headers=lock.headers())
    if error == "down" or code is None:
        return LcuResult.down()
    if code == 404:
        return LcuResult("open", queue_id=queue_id, board=board)
    if code != 200 or not isinstance(body, dict):
        return LcuResult("error", detail="Champion select is unavailable.", queue_id=queue_id, board=board)
    try:
        pickable = _fetch_pickable(lock)
        select = parse_session(body, pickable)
    except Exception:
        return LcuResult("error", detail="Champion select is unavailable.", queue_id=queue_id, board=board)
    return LcuResult("champselect", select=select, queue_id=queue_id, board=board)
