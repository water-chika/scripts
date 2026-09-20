#!/usr/bin/env python3
"""Regression test for sway_start.sh's environment sanitising.

The bug this guards against: sway_start.sh ran bare `sway`, so when it was
invoked from inside an existing Wayland session it inherited WAYLAND_DISPLAY
and SWAYSOCK, wlroots picked the wayland backend, and a nested
"wlroots - WL-1" window opened on the user's live desktop. Every such instance
leaked, so windows kept appearing on their own.

We stub `sway` on PATH with a recorder and assert on the environment the real
binary would have been handed.

Run: python3 tests/test_sway_start.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sway_start.sh"

STUB = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["SWAY_STUB_OUT"], "w") as fh:
    json.dump({"env": dict(os.environ), "argv": sys.argv[1:]}, fh)
"""

# A session-ish environment, as inherited by anything started from a terminal
# on the running desktop.
SESSION_ENV = {
    "WAYLAND_DISPLAY": "wayland-1",
    "SWAYSOCK": "/run/user/1000/sway-ipc.1000.2280.sock",
    "DISPLAY": ":0",
}

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def run(extra_env, args=()):
    """Run sway_start.sh with a stubbed sway; return what sway received."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        stub = td / "sway"
        stub.write_text(STUB)
        stub.chmod(0o755)
        out = td / "record.json"

        env = {
            "PATH": f"{td}:/usr/bin:/bin",
            "HOME": str(td),
            "SWAY_STUB_OUT": str(out),
        }
        env.update(extra_env)

        proc = subprocess.run(
            ["sh", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if not out.exists():
            raise AssertionError(
                f"stub sway was never executed (rc={proc.returncode}): "
                f"{proc.stdout}{proc.stderr}"
            )
        return json.loads(out.read_text())


print("case 1: invoked from inside a live session -> must go headless")
rec = run(SESSION_ENV)
env = rec["env"]
# These three are the actual bug: leaking any of them lets wlroots pick a
# backend that draws on the user's desktop.
for var in ("WAYLAND_DISPLAY", "SWAYSOCK", "DISPLAY"):
    check(f"{var} is unset", var not in env, f"got {env.get(var)!r}")
check(
    "WLR_BACKENDS=headless",
    env.get("WLR_BACKENDS") == "headless",
    f"got {env.get('WLR_BACKENDS')!r}",
)
check(
    "WLR_LIBINPUT_NO_DEVICES=1",
    env.get("WLR_LIBINPUT_NO_DEVICES") == "1",
    f"got {env.get('WLR_LIBINPUT_NO_DEVICES')!r}",
)
check("fcitx IM module still exported", env.get("GTK_IM_MODULE") == "fcitx")

print("case 2: invoked from a TTY -> must start the real session unchanged")
rec = run({})
env = rec["env"]
check(
    "WLR_BACKENDS not forced",
    "WLR_BACKENDS" not in env,
    f"got {env.get('WLR_BACKENDS')!r}",
)
check("fcitx IM module still exported", env.get("QT_IM_MODULE") == "fcitx")

print("case 3: a visible nested window is opt-in, not accidental")
for label, extra, args in (
    ("--nested flag", SESSION_ENV, ("--nested",)),
    ("SWAY_START_NESTED=1", {**SESSION_ENV, "SWAY_START_NESTED": "1"}, ()),
):
    rec = run(extra, args)
    env = rec["env"]
    check(
        f"{label}: session kept",
        env.get("WAYLAND_DISPLAY") == "wayland-1",
        f"got {env.get('WAYLAND_DISPLAY')!r}",
    )
    check(
        f"{label}: not forced headless",
        env.get("WLR_BACKENDS") != "headless",
    )
    check(f"{label}: flag not passed to sway", "--nested" not in rec["argv"])

print("case 4: extra arguments reach sway")
rec = run(SESSION_ENV, ("-c", "/tmp/x.conf"))
check("argv forwarded", rec["argv"] == ["-c", "/tmp/x.conf"], f"got {rec['argv']}")

if failures:
    print(f"\nFAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("\nall checks passed")
