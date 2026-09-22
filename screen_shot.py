#!/usr/bin/env python3
"""screen_shot.py - port of screen_shot.sh: select a screen region and get it
on the clipboard, with a saved file too where the platform makes that part
of the same action.

Linux: unchanged behaviour - `slurp` (region select) | `grim -g -` (capture)
-> a timestamped PNG under ~/Pictures, then `wl-copy` puts that file's bytes
on the clipboard. All three are external Wayland tools; this script does not
invent a fallback for a missing one; it says which one is missing (via
shutil.which) instead of failing on a bare "command not found".

Windows: there is no slurp/grim/wl-copy equivalent worth shelling out to.
Windows 10 1809+ ships its own region-capture-to-clipboard tool as a URI
protocol handler: `ms-screenclip:` opens the built-in Snip & Sketch region
picker, and whatever the user selects is copied to the clipboard directly
by that tool - no PNG is written to disk by this script on Windows, which
is the one real behavioural difference from the Linux path (documented here
rather than silently losing the "also saved a file" half of the contract).
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

import _common as sh


def linux_screenshot() -> int:
    for tool, hint in (
        ("slurp", "region selection; pacman -S slurp / apt install slurp"),
        ("grim", "screen capture; pacman -S grim / apt install grim"),
        ("wl-copy", "clipboard; pacman -S wl-clipboard / apt install wl-clipboard"),
    ):
        sh.which_or_die(tool, hint, exit_code=3)

    pictures = Path.home() / "Pictures"
    pictures.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    filename = pictures / f"screenshot_{stamp}.png"

    rc, geometry, _ = sh.run(["slurp"])
    if rc != 0 or not geometry.strip():
        sh.die("slurp: no region selected (or slurp failed)", 3)

    with open(filename, "wb") as fh:
        proc = subprocess.run(["grim", "-g", geometry.strip(), "-"], stdout=fh, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sh.die(f"grim failed: {proc.stderr.decode(sh.CONSOLE_ENCODING, errors='replace')}", 3)

    with open(filename, "rb") as fh:
        proc = subprocess.run(["wl-copy"], stdin=fh, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sh.die(f"wl-copy failed: {proc.stderr.decode(sh.CONSOLE_ENCODING, errors='replace')}", 3)

    print(f"screen_shot: saved {filename} and copied it to the clipboard")
    return 0


def windows_screenshot() -> int:
    # os.startfile() is the portable way to invoke a URI protocol handler on
    # Windows without building a shell string; it is a no-op stub on
    # non-Windows Pythons, which is exactly why this branch is gated on
    # sh.WINDOWS rather than relying on AttributeError to route it.
    try:
        os.startfile("ms-screenclip:")  # type: ignore[attr-defined]
    except OSError as e:
        sh.die(f"could not launch the Snip & Sketch region tool: {e}", 3)
    print(
        "screen_shot: region picker opened - select a region; it copies to the "
        "clipboard directly (no file is saved by this script on Windows)"
    )
    return 0


def main() -> int:
    if sh.WINDOWS:
        return windows_screenshot()
    return linux_screenshot()


if __name__ == "__main__":
    raise SystemExit(main())
