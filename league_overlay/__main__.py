"""Start the overlay: py -m league_overlay"""

from __future__ import annotations

import argparse
import ctypes
import sys


def enable_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Always-on-top League of Legends shop and champion-select overlay.")
    parser.add_argument("--once", action="store_true", help="Print one status and exit.")
    parser.add_argument("--demo-seconds", type=float, default=0, help="Close the window after N seconds.")
    parser.add_argument("--self-check", action="store_true", help="Open the window, verify click-through, then exit.")
    parser.add_argument("--debug", action="store_true", help="Print every poll.")
    return parser.parse_args(argv)


def run_once(debug: bool) -> int:
    from league_overlay.poller import Poller

    poller = Poller(debug=debug)
    poller.catalog.ensure()
    view = poller.tick()
    print(view.headline, flush=True)
    if view.ingame.message:
        print(f"In game: {view.ingame.message}", flush=True)
    elif view.ingame.champion_line:
        print(f"In game: {view.ingame.champion_line}", flush=True)
    if view.picks.message:
        print(f"Champion select: {view.picks.message}", flush=True)
    elif view.picks.pick_line:
        print(f"Champion select: {view.picks.pick_line}", flush=True)
    if view.warning:
        print(view.warning, flush=True)
    return 0


def run_window(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        print("The overlay uses Windows always-on-top and click-through.")
        print("Run it on the Windows PC where League is installed.")
        return 1
    try:
        import tkinter  # noqa: F401
    except Exception as exc:
        print(f"tkinter is not available: {exc}")
        print("Install Python from https://www.python.org/downloads/windows/ and include tcl/tk and the py launcher.")
        return 1
    enable_dpi()
    from league_overlay.poller import Poller
    from league_overlay.ui import OverlayWindow

    poller = Poller(debug=args.debug)
    if args.self_check:
        poller.catalog.ensure()
        view = poller.tick()
        print(view.headline, flush=True)
        window = OverlayWindow(poller)
        ok = window.verify_clickthrough()
        window.close()
        print("SELF_CHECK_OK" if ok else "SELF_CHECK_FAIL", flush=True)
        return 0 if ok else 1
    print("League overlay", flush=True)
    print("League has to be running on this PC.", flush=True)
    poller.start()
    OverlayWindow(poller, demo_seconds=args.demo_seconds).run()
    poller.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.once:
        return run_once(args.debug)
    return run_window(args)


if __name__ == "__main__":
    sys.exit(main())
