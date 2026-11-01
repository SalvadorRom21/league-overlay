"""League client (LCU) via the local lockfile. The password never leaves this PC."""

from __future__ import annotations

import base64
import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass
class LcuResult:
    status: str
    select: ChampSelect | None = None
    detail: str = ""

    @staticmethod
    def down() -> LcuResult:
        return LcuResult("down")


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
    return ChampSelect(
        allies=allies,
        enemies=enemies,
        bans=sorted(bans),
        pickable=resolved,
        position=position,
        locked_id=locked,
        local_champion_id=local_champion or locked,
    )


def _fetch_pickable(lock: Lockfile) -> list[int] | None:
    code, body, error = local_json(
        lock.url("/lol-champ-select/v1/pickable-champion-ids"),
        headers=lock.headers(),
    )
    if error or code != 200 or not isinstance(body, list):
        return None
    return _positive_ids(body)


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
    code, body, error = local_json(lock.url("/lol-champ-select/v1/session"), headers=lock.headers())
    if error == "down" or code is None:
        return LcuResult.down()
    if code == 404:
        return LcuResult("open")
    if code != 200 or not isinstance(body, dict):
        return LcuResult("error", detail="Champion select is unavailable.")
    try:
        pickable = _fetch_pickable(lock)
        select = parse_session(body, pickable)
    except Exception:
        return LcuResult("error", detail="Champion select is unavailable.")
    return LcuResult("champselect", select=select)
