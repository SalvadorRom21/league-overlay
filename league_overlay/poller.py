"""Background polling. Fast during a game or champion select, slow when idle."""

from __future__ import annotations

import threading
import traceback

from league_overlay.augments import AugmentBook
from league_overlay.catalog import Catalog
from league_overlay.lcu import LcuResult, fetch_lcu
from league_overlay.live import LiveResult, fetch_live
from league_overlay.paths import CACHE, DRAGON_CACHE
from league_overlay.screen_augments import ScreenWatcher
from league_overlay.view import IDLE_INTERVAL, OverlayView, build_view


class Poller:
    def __init__(self, debug: bool = False) -> None:
        self.catalog = Catalog(DRAGON_CACHE)
        self.augments = AugmentBook(CACHE / "augments.json")
        self.debug = debug
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_print: str | None = None
        self._screen = ScreenWatcher()
        self._view, self._interval = self._safe_view(initial=True)

    def start(self) -> None:
        self._screen.start()
        threading.Thread(target=self.catalog.ensure, name="ddragon", daemon=True).start()
        threading.Thread(target=self._ensure_augments, name="augments", daemon=True).start()
        threading.Thread(target=self._loop, name="league-poll", daemon=True).start()

    def snapshot(self) -> OverlayView:
        with self._lock:
            return self._view

    def tick(self) -> OverlayView:
        view, interval = self._safe_view(initial=False)
        with self._lock:
            self._view = view
            self._interval = interval
        return view

    def stop(self) -> None:
        self._stop.set()
        self._screen.stop()

    def _safe_view(self, initial: bool) -> tuple[OverlayView, float]:
        if initial:
            return build_view(LiveResult.down(), LcuResult.down(), self.catalog.snapshot(), self.augments)
        try:
            live = fetch_live()
            lcu = fetch_lcu()
            self._screen.update(live.data, lcu.queue_id, self.augments)
            return build_view(live, lcu, self.catalog.snapshot(), self.augments, self._screen.snapshot())
        except Exception:
            traceback.print_exc()
            return build_view(LiveResult("error"), LcuResult("error"), self.catalog.snapshot())

    def _print(self, view: OverlayView) -> None:
        line = view.headline
        if line == self._last_print and not self.debug:
            return
        self._last_print = line
        print(line, flush=True)
        if view.ingame.message:
            print(f"In game: {view.ingame.message}", flush=True)
        elif view.ingame.champion_line:
            print(f"In game: {view.ingame.champion_line}", flush=True)
        if view.ingame.detail_line:
            print(view.ingame.detail_line, flush=True)
        for buy in view.ingame.buys:
            print(f"{buy.title}: {buy.item_line} {buy.into_line}", flush=True)
        if view.picks.message:
            print(f"Champion select: {view.picks.message}", flush=True)
        elif view.picks.pick_line:
            print(f"Champion select: {view.picks.pick_line}", flush=True)

    def _ensure_augments(self) -> None:
        try:
            self.augments.ensure()
        except Exception:
            traceback.print_exc()

    def _loop(self) -> None:
        while not self._stop.is_set():
            view = self.tick()
            self._print(view)
            with self._lock:
                interval = self._interval
            self._stop.wait(interval)

