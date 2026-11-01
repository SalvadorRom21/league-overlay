# League overlay

A small always-on-top window for League of Legends on Windows. During a game it reads the local live client and recommends the next component to buy against the enemy team. During champion select, when the local client can be read, it suggests a champion you can actually lock.

It does not buy items, click the shop, or inject anything into the game. Advice is a documented heuristic in [HEURISTIC.md](HEURISTIC.md). It does not use win rates.

League of Legends has to be running on this same PC. The live client and the client lockfile are only available locally.

## Run

From this folder:

```
py -m league_overlay
```

Or double-click `run.bat`, or run `run.bat` from a terminal in this folder.

Leave that terminal open. Closing it stops the overlay. Ctrl+Shift+Q also quits.

The first launch should be online. The app downloads champion and item data from Riot Data Dragon into `cache/` and reuses it offline after that. `cache/` is not part of the git repo.

### If `py` is missing

1. Install Python 3.11 or newer from <https://www.python.org/downloads/windows/>.
2. In the installer, enable **py launcher** and **tcl/tk and IDLE**.
3. Open a new terminal in this folder and run `py -m league_overlay`.

No extra packages are required. The app uses the Python standard library (tkinter, the Windows API, and urllib).

## What you see

The window starts in the top-right corner. Drag the title once interaction is on. The position is remembered in `cache/window.json`.

| State | What it means |
| --- | --- |
| **Waiting for League** | League is not running here, or the local APIs are closed. |
| **League is open** | The client is up. Waiting for champion select or a game. |
| **In game** | Next buy, then the completed item, and why it answers this enemy team. |
| **Champion select** | A suggested pick from the champions you can lock. |

Both panels stay on screen. The active one has a gold border.

If champion select cannot be read, the panel says **Champion select is unavailable** and the in-game buyer still runs.

While a game or champion select is active the app polls about three times a second. When nothing is active it polls every two seconds. Errors and a closed client do not crash the window.

## Hotkeys

| Keys | Action |
| --- | --- |
| Ctrl+Shift+O | Toggle click-through. The window starts click-through so it does not steal clicks from the game. Press this to drag it or hit the close mark. |
| Ctrl+Shift+H | Hide or show the overlay. |
| Ctrl+Shift+Q | Quit. |

The footer of the window shows the keys Windows actually accepted. If another program already owns Ctrl+Shift+O (Discord and NVIDIA Broadcast are common), the overlay uses Ctrl+Alt+O instead, and the same fallback applies to hide (Ctrl+Alt+H) and quit (Ctrl+Alt+Q). The terminal prints the chords that registered.

## League setup

- Run League on this PC, not a remote stream of someone else's game.
- Use **Borderless** or **Windowed**. Exclusive fullscreen can cover any overlay.
- The live client is `https://127.0.0.1:2999/liveclientdata/allgamedata`. It exists only during a game. Certificate checks are turned off for that localhost port and for the local client lockfile. Public Data Dragon downloads still verify TLS.
- Champion select is read from the League lockfile (`League of Legends\lockfile`): port, protocol, and the remoting auth token. That token stays on this machine and is never written to the repo or the terminal.

## Checks

```
py -m unittest discover -s tests -t .
py -m league_overlay --once
```

`--once` prints the current status and exits. With League closed, the status is `Waiting for League`.
