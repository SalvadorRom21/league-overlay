"""Windows always-on-top, click-through, and global hotkeys."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOPMOST = ctypes.c_void_p(-1)
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
MOD_ALT = 0x0001
MOD_SHIFT = 0x0004
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
GA_ROOT = 2
VK_O = 0x4F
VK_H = 0x48
VK_Q = 0x51

HOTKEY_INTERACT = 1
HOTKEY_HIDE = 2
HOTKEY_QUIT = 3

_bound = False
_registered: list[int] = []

# Ctrl+Shift is the default. Ctrl+Alt is the fallback when another app already owns the chord.
_HOTKEY_CANDIDATES = {
    "interact": (
        (HOTKEY_INTERACT, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_O, "Ctrl+Shift+O"),
        (HOTKEY_INTERACT, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_O, "Ctrl+Alt+O"),
    ),
    "hide": (
        (HOTKEY_HIDE, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_H, "Ctrl+Shift+H"),
        (HOTKEY_HIDE, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_H, "Ctrl+Alt+H"),
    ),
    "quit": (
        (HOTKEY_QUIT, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_Q, "Ctrl+Shift+Q"),
        (HOTKEY_QUIT, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_Q, "Ctrl+Alt+Q"),
    ),
}


def style_with_clickthrough(style: int, clickthrough: bool) -> int:
    """Pure bit math so tests can check click-through without a window."""
    style |= WS_EX_LAYERED
    if clickthrough:
        style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
    else:
        style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
    return style


def _bind() -> None:
    global _bound
    if _bound:
        return
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    get_long, set_long = _long_ptr()
    get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    get_long.restype = ctypes.c_ssize_t
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_long.restype = ctypes.c_ssize_t
    _bound = True


def _long_ptr():
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
    return user32.GetWindowLongW, user32.SetWindowLongW


def top_hwnd(tk_id: int) -> int:
    _bind()
    root = user32.GetAncestor(tk_id, GA_ROOT)
    return int(root or tk_id)


def current_exstyle(hwnd: int) -> int:
    _bind()
    get_long, _set_long = _long_ptr()
    return int(get_long(hwnd, GWL_EXSTYLE))


def apply_clickthrough(hwnd: int, clickthrough: bool) -> None:
    _bind()
    get_long, set_long = _long_ptr()
    style = style_with_clickthrough(int(get_long(hwnd, GWL_EXSTYLE)), clickthrough)
    set_long(hwnd, GWL_EXSTYLE, style)
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def force_topmost(hwnd: int) -> None:
    _bind()
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def register_hotkeys() -> dict[str, str]:
    """Register interact, hide, and quit. Values are the chord Windows accepted, or empty."""
    _bind()
    unregister_hotkeys()
    bound: dict[str, str] = {}
    for name, candidates in _HOTKEY_CANDIDATES.items():
        bound[name] = ""
        for hotkey_id, mods, virtual_key, label in candidates:
            if user32.RegisterHotKey(None, hotkey_id, mods, virtual_key):
                _registered.append(hotkey_id)
                bound[name] = label
                break
    return bound


def unregister_hotkeys() -> None:
    _bind()
    for hotkey_id in list(_registered):
        user32.UnregisterHotKey(None, hotkey_id)
    _registered.clear()


def poll_hotkeys() -> list[int]:
    _bind()
    fired: list[int] = []
    message = wintypes.MSG()
    while user32.PeekMessageW(ctypes.byref(message), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
        fired.append(int(message.wParam))
    return fired
