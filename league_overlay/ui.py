"""Small always-on-top overlay. Click-through until Ctrl+Shift+O."""

from __future__ import annotations

import json

import tkinter as tk

from league_overlay.paths import CACHE, WINDOW_STATE
from league_overlay.poller import Poller
from league_overlay.view import BuyView, OverlayView
from league_overlay.winutil import (
    apply_clickthrough,
    force_topmost,
    poll_hotkeys,
    register_hotkeys,
    top_hwnd,
    unregister_hotkeys,
    HOTKEY_HIDE,
    HOTKEY_INTERACT,
    HOTKEY_QUIT,
    WS_EX_TRANSPARENT,
    current_exstyle,
)

BG = "#12151c"
CARD = "#1b212c"
BORDER = "#2c3544"
GOLD = "#c8aa6e"
TEXT = "#e7edf5"
MUTED = "#93a0b4"
GREEN = "#7ddea5"
AMBER = "#e3b341"
WIDTH = 392


def _font(size: int, bold: bool = False) -> tuple[str, int, str]:
    return ("Segoe UI", size, "bold" if bold else "normal")


class OverlayWindow:
    def __init__(self, poller: Poller, demo_seconds: float = 0) -> None:
        self.poller = poller
        self.interactive = False
        self.hidden = False
        self._closed = False
        self._hwnd = 0
        self._signature: tuple | None = None
        self._placed = False
        self.root = tk.Tk()
        self.root.title("League Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg=GOLD)
        self.outer = tk.Frame(self.root, bg=GOLD)
        self.outer.pack(fill="both", expand=True)
        self.body = tk.Frame(self.outer, bg=BG)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(self.body, bg=BG)
        header.pack(fill="x", padx=10, pady=(8, 0))
        self.header = header
        self.title = tk.Label(header, text="League overlay", fg=TEXT, bg=BG, font=_font(11, True))
        self.title.pack(side="left")
        self.mode_pill = tk.Label(header, text="WAITING", fg=MUTED, bg="#2a303c", font=_font(8, True), padx=6, pady=1)
        self.mode_pill.pack(side="left", padx=(8, 0))
        self.interact_pill = tk.Label(
            header, text="CLICK-THROUGH", fg=MUTED, bg="#2a303c", font=_font(8, True), padx=6, pady=1
        )
        self.interact_pill.pack(side="left", padx=(6, 0))
        self.close_button = tk.Label(header, text="×", fg=MUTED, bg=BG, font=_font(12, True), cursor="hand2")
        self.close_button.pack(side="right")
        self.close_button.bind("<Button-1>", lambda _event: self.close())

        self.status = tk.Label(self.body, text="Waiting for League", fg=TEXT, bg=BG, font=_font(16, True), anchor="w")
        self.status.pack(fill="x", padx=10, pady=(6, 0))
        self.note = tk.Label(
            self.body, text="", fg=MUTED, bg=BG, font=_font(8), anchor="w", justify="left", wraplength=WIDTH - 28
        )
        self.note.pack(fill="x", padx=10, pady=(2, 0))
        self.warning = tk.Label(
            self.body, text="", fg=AMBER, bg=BG, font=_font(8), anchor="w", justify="left", wraplength=WIDTH - 28
        )

        self.game_card, self.game_title, self.game_message = self._card("IN GAME")
        self.game_champion = self._line(self.game_card, 10, True)
        self.game_enemies = self._line(self.game_card, 8, False, MUTED)
        self.game_threats = self._line(self.game_card, 8, False, GOLD)
        self.game_items = self._line(self.game_card, 8, False, MUTED)
        self.buy_blocks = (self._buy_block(self.game_card), self._buy_block(self.game_card))

        self.pick_card, self.pick_title, self.pick_message = self._card("CHAMPION SELECT")
        self.pick_choice = self._line(self.pick_card, 11, True)
        self.pick_why = self._line(self.pick_card, 8, False, TEXT)
        self.pick_alts = self._line(self.pick_card, 8, False, MUTED)
        self.pick_teams = self._line(self.pick_card, 8, False, MUTED)
        self.pick_meta = self._line(self.pick_card, 8, False, MUTED)

        self.footer = tk.Label(
            self.body,
            text="Ctrl+Shift+O interact    Ctrl+Shift+H hide    Ctrl+Shift+Q quit",
            fg=MUTED,
            bg=BG,
            font=_font(8),
            anchor="w",
        )
        self.footer.pack(fill="x", padx=10, pady=(6, 8))
        self._bind_drag(self.header)
        self._bind_drag(self.title)
        self.hotkeys = register_hotkeys()
        self._announce_hotkeys()
        self.root.update_idletasks()
        self._hwnd = top_hwnd(self.root.winfo_id())
        self._apply_style()
        self._render(self.poller.snapshot())
        self._demo_after = None
        if demo_seconds > 0:
            self._demo_after = self.root.after(int(demo_seconds * 1000), self.close)
        self._hotkey_after = self.root.after(50, self._hotkey_loop)
        self._refresh_after = self.root.after(200, self._refresh_loop)
        self._raise_after = self.root.after(1000, self._raise)

    def _announce_hotkeys(self) -> None:
        actions = (("interact", "interact"), ("hide", "hide"), ("quit", "quit"))
        parts: list[str] = []
        for name, action in actions:
            label = self.hotkeys.get(name) or ""
            if label:
                parts.append(f"{label} {action}")
                print(f"{label}  {action}", flush=True)
            else:
                print(f"No free hotkey for {action}.", flush=True)
        self.footer.configure(text="    ".join(parts) or "Hotkeys did not register")

    def _card(self, title: str) -> tuple[tk.Frame, tk.Label, tk.Label]:
        frame = tk.Frame(self.body, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        frame.pack(fill="x", padx=10, pady=(8, 0))
        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="x", padx=8, pady=6)
        label = tk.Label(inner, text=title, fg=GOLD, bg=CARD, font=_font(8, True), anchor="w")
        label.pack(fill="x")
        message = tk.Label(
            inner, text="", fg=TEXT, bg=CARD, font=_font(10), anchor="w", justify="left", wraplength=WIDTH - 44
        )
        frame.inner = inner  # type: ignore[attr-defined]
        return frame, label, message

    def _line(self, card: tk.Frame, size: int, bold: bool, color: str = TEXT) -> tk.Label:
        parent = card.inner  # type: ignore[attr-defined]
        label = tk.Label(
            parent,
            text="",
            fg=color,
            bg=CARD,
            font=_font(size, bold),
            anchor="w",
            justify="left",
            wraplength=WIDTH - 44,
        )
        return label

    def _buy_block(self, card: tk.Frame) -> dict[str, tk.Label]:
        parent = card.inner  # type: ignore[attr-defined]
        title = tk.Label(parent, text="", fg=GOLD, bg=CARD, font=_font(8, True), anchor="w")
        item = tk.Label(parent, text="", fg=TEXT, bg=CARD, font=_font(10, True), anchor="w", justify="left", wraplength=WIDTH - 44)
        into = tk.Label(parent, text="", fg=MUTED, bg=CARD, font=_font(9), anchor="w", justify="left", wraplength=WIDTH - 44)
        why = tk.Label(parent, text="", fg=TEXT, bg=CARD, font=_font(8), anchor="w", justify="left", wraplength=WIDTH - 44)
        return {"title": title, "item": item, "into": into, "why": why}

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._press)
        widget.bind("<B1-Motion>", self._motion)
        widget.bind("<ButtonRelease-1>", self._release)

    def _press(self, event: tk.Event) -> None:
        if not self.interactive:
            return
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _motion(self, event: tk.Event) -> None:
        if not self.interactive:
            return
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{int(x)}+{int(y)}")

    def _release(self, _event: tk.Event) -> None:
        if self.interactive:
            self._save_position()

    def _initial_xy(self, width: int, height: int) -> tuple[int, int]:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        default = (max(0, screen_w - width - 16), 16)
        try:
            saved = json.loads(WINDOW_STATE.read_text(encoding="utf-8"))
            x, y = int(saved["x"]), int(saved["y"])
        except (OSError, ValueError, TypeError, KeyError):
            return default
        if 0 <= x <= screen_w - 40 and 0 <= y <= screen_h - 40:
            return x, y
        return default

    def _save_position(self) -> None:
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            payload = {"x": self.root.winfo_x(), "y": self.root.winfo_y()}
            WINDOW_STATE.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    def _fit(self) -> None:
        self.root.update_idletasks()
        height = max(self.outer.winfo_reqheight(), 80)
        if not self._placed:
            x, y = self._initial_xy(WIDTH, height)
            self._placed = True
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        self.root.geometry(f"{WIDTH}x{height}+{int(x)}+{int(y)}")

    def _apply_style(self) -> None:
        if not self._hwnd:
            return
        apply_clickthrough(self._hwnd, not self.interactive)
        cursor = "fleur" if self.interactive else "arrow"
        self.header.configure(cursor=cursor)
        self.title.configure(cursor=cursor)
        if self.interactive:
            self.interact_pill.configure(text="INTERACTIVE", fg="#04210f", bg=GREEN)
        else:
            self.interact_pill.configure(text="CLICK-THROUGH", fg=MUTED, bg="#2a303c")

    def toggle_interact(self) -> None:
        self.interactive = not self.interactive
        if self.hidden:
            self.hidden = False
            self.root.deiconify()
        self._apply_style()
        print("Interactive" if self.interactive else "Click-through", flush=True)

    def toggle_hide(self) -> None:
        self.hidden = not self.hidden
        if self.hidden:
            self.root.withdraw()
            print("Hidden", flush=True)
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self._apply_style()
            print("Shown", flush=True)

    def _raise(self) -> None:
        if self._closed:
            return
        if not self.hidden and self._hwnd:
            self.root.attributes("-topmost", True)
            force_topmost(self._hwnd)
        if not self._closed:
            self._raise_after = self.root.after(1000, self._raise)

    def _hotkey_loop(self) -> None:
        if self._closed:
            return
        for hotkey_id in poll_hotkeys():
            if hotkey_id == HOTKEY_INTERACT:
                self.toggle_interact()
            elif hotkey_id == HOTKEY_HIDE:
                self.toggle_hide()
            elif hotkey_id == HOTKEY_QUIT:
                self.close()
                return
        if not self._closed:
            self._hotkey_after = self.root.after(50, self._hotkey_loop)

    def _refresh_loop(self) -> None:
        if self._closed:
            return
        try:
            self._render(self.poller.snapshot())
        except Exception:
            traceback_print()
        if not self._closed:
            self._refresh_after = self.root.after(200, self._refresh_loop)

    def _render(self, view: OverlayView) -> None:
        signature = (
            view.mode,
            view.headline,
            view.note,
            view.warning,
            view.ingame,
            view.picks,
            self.interactive,
        )
        if signature == self._signature:
            return
        self._signature = signature
        self.status.configure(text=view.headline, fg=GOLD if view.mode in {"ingame", "champselect"} else TEXT)
        self.note.configure(text=view.note)
        self._show(self.warning, bool(view.warning), text=view.warning, before=self.game_card)
        self._paint_mode(view.mode)
        self._paint_game(view)
        self._paint_picks(view)
        self._fit()

    def _paint_mode(self, mode: str) -> None:
        styles = {
            "ingame": ("IN GAME", "#04210f", GREEN),
            "champselect": ("SELECT", "#2a2412", GOLD),
            "idle": ("OPEN", "#2a303c", TEXT),
            "waiting": ("WAITING", "#2a303c", MUTED),
        }
        text, bg, fg = styles.get(mode, styles["waiting"])
        self.mode_pill.configure(text=text, bg=bg, fg=fg)
        active_game = mode == "ingame"
        active_pick = mode == "champselect"
        self._border(self.game_card, active_game)
        self._border(self.pick_card, active_pick)

    def _border(self, card: tk.Frame, active: bool) -> None:
        color = GOLD if active else BORDER
        card.configure(highlightbackground=color, highlightcolor=color)

    def _paint_game(self, view: OverlayView) -> None:
        panel = view.ingame
        for label in (
            self.game_message,
            self.game_champion,
            self.game_enemies,
            self.game_threats,
            self.game_items,
        ):
            self._pack_line(label, False)
        for block in self.buy_blocks:
            for label in block.values():
                self._pack_line(label, False)
        self._pack_line(self.game_message, bool(panel.message), text=panel.message)
        self._pack_line(self.game_champion, bool(panel.champion_line), text=panel.champion_line)
        self._pack_line(self.game_enemies, bool(panel.enemy_line), text=panel.enemy_line)
        self._pack_line(self.game_threats, bool(panel.threat_line), text=panel.threat_line)
        self._pack_line(self.game_items, bool(panel.items_line), text=panel.items_line)
        for index, block in enumerate(self.buy_blocks):
            buy = panel.buys[index] if index < len(panel.buys) else None
            self._paint_buy(block, buy)

    def _paint_buy(self, block: dict[str, tk.Label], buy: BuyView | None) -> None:
        if buy is None:
            for label in block.values():
                self._pack_line(label, False)
            return
        color = GREEN if buy.affordable else AMBER
        self._pack_line(block["title"], True, text=buy.title)
        block["item"].configure(fg=color)
        self._pack_line(block["item"], True, text=buy.item_line)
        self._pack_line(block["into"], bool(buy.into_line), text=buy.into_line)
        self._pack_line(block["why"], bool(buy.why), text=buy.why)

    def _paint_picks(self, view: OverlayView) -> None:
        panel = view.picks
        for label in (
            self.pick_message,
            self.pick_choice,
            self.pick_why,
            self.pick_alts,
            self.pick_teams,
            self.pick_meta,
        ):
            self._pack_line(label, False)
        self._pack_line(self.pick_message, bool(panel.message), text=panel.message)
        self._pack_line(self.pick_choice, bool(panel.pick_line), text=panel.pick_line)
        self._pack_line(self.pick_why, bool(panel.why), text=panel.why)
        self._pack_line(self.pick_alts, bool(panel.alt_line), text=panel.alt_line)
        self._pack_line(self.pick_teams, bool(panel.team_line), text=panel.team_line)
        self._pack_line(self.pick_meta, bool(panel.meta_line), text=panel.meta_line)

    def _pack_line(self, label: tk.Label, show: bool, text: str | None = None) -> None:
        if text is not None:
            label.configure(text=text)
        if show:
            if not label.winfo_ismapped():
                label.pack(fill="x", pady=(1, 0))
        elif label.winfo_ismapped():
            label.pack_forget()

    def _show(self, label: tk.Label, show: bool, text: str = "", before: tk.Widget | None = None) -> None:
        if text:
            label.configure(text=text)
        if show:
            if not label.winfo_ismapped():
                label.pack(fill="x", padx=10, pady=(4, 0), before=before)
        elif label.winfo_ismapped():
            label.pack_forget()

    def verify_clickthrough(self) -> bool:
        self.root.update_idletasks()
        self.root.update()
        self._hwnd = top_hwnd(self.root.winfo_id())
        self.interactive = False
        self._apply_style()
        self.root.update()
        hidden = current_exstyle(self._hwnd)
        self.interactive = True
        self._apply_style()
        self.root.update()
        shown = current_exstyle(self._hwnd)
        self.interactive = False
        self._apply_style()
        passed = bool(hidden & WS_EX_TRANSPARENT) and not bool(shown & WS_EX_TRANSPARENT)
        if not passed:
            print(f"click-through styles: through={hidden:#x} interact={shown:#x}", flush=True)
        return passed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for after_id in (
            getattr(self, "_demo_after", None),
            getattr(self, "_hotkey_after", None),
            getattr(self, "_refresh_after", None),
            getattr(self, "_raise_after", None),
        ):
            if not after_id:
                continue
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        try:
            unregister_hotkeys()
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass

    def run(self) -> None:
        self.root.mainloop()


def traceback_print() -> None:
    import traceback

    traceback.print_exc()
