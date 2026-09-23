"""Shared helpers for the Python ports of the host/viewer glue scripts
(rfb_view.py, vm_view.py, banana_view.py, screen_shot.py, ssh_agent.py,
add_path.py).

One module instead of copy-pasting the same subprocess/encoding/which
boilerplate into six files - see daily-session-optimization/scripts/probe.py
in copilot-automation for the sibling pattern this follows: one portable
tool per job, platform branches only where the underlying facility genuinely
differs, not a bash file and a PowerShell file that drift apart.

Every subprocess call in this repo's Python ports goes through run() so that
none of them can repeat the cp1252 UnicodeDecodeError this codebase has hit
before from bare text=True with no encoding= (see
copilot-automation/daily-session-optimization/scripts/multiplexer.py's
CONSOLE_ENCODING for the sibling fix on the other repo).
"""

from __future__ import annotations

import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# Same fix as multiplexer.CONSOLE_ENCODING: the console/locale encoding, not a
# hardcoded UTF-8 assumption, and always with errors="replace" so mangled
# bytes never crash the caller outright.
CONSOLE_ENCODING = locale.getpreferredencoding(False)

WINDOWS = os.name == "nt"


def run(argv: Sequence[str], timeout: Optional[float] = None,
        input_text: Optional[str] = None) -> Tuple[int, str, str]:
    """Run argv (a list - never a shell string), returning (rc, stdout,
    stderr) as text decoded with CONSOLE_ENCODING/errors=replace. rc=127 on a
    missing binary, matching what a POSIX shell reports for `command not
    found` (mirrors probe.py's convention in copilot-automation)."""
    try:
        res = subprocess.run(
            list(argv), capture_output=True, timeout=timeout,
            input=input_text.encode(CONSOLE_ENCODING) if input_text is not None else None,
        )
        return (
            res.returncode,
            res.stdout.decode(CONSOLE_ENCODING, errors="replace"),
            res.stderr.decode(CONSOLE_ENCODING, errors="replace"),
        )
    except FileNotFoundError:
        return 127, "", ""
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(CONSOLE_ENCODING, errors="replace") if e.stdout else ""
        err = e.stderr.decode(CONSOLE_ENCODING, errors="replace") if e.stderr else ""
        return 124, out, err


def which_or_die(name: str, hint: str, exit_code: int = 3) -> str:
    """shutil.which() - never assume a name resolves the same way on both
    platforms (Windows needs PATHEXT, e.g. an .exe/.cmd suffix, which()
    already handles that; a bare os.path.isfile(name) would not)."""
    found = shutil.which(name)
    if not found:
        die(f"{name} not found on PATH. {hint}", exit_code)
    return found


def die(message: str, exit_code: int = 1) -> None:
    print(f"{Path(sys.argv[0]).name}: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def ssh_argv(host: str, remote_args: Sequence[str], connect_timeout: int = 8) -> List[str]:
    """A plain argv list, run through run()/Popen - never a shell string, so
    no quoting games are needed on either platform. ssh itself (OpenSSH
    client) is what must be on PATH; it ships with Windows 10+ by default."""
    return [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}",
        host, *remote_args,
    ]


def runtime_dir() -> Path:
    """Where to drop viewer/tunnel logs. XDG_RUNTIME_DIR on Linux, %TEMP% on
    Windows, /tmp as a last resort - never assume /tmp exists or that
    forward-slash paths are valid (Windows paths are not)."""
    if WINDOWS:
        return Path(os.environ.get("TEMP", os.environ.get("TMP", ".")))
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))


def local_port_listening(port: int) -> bool:
    """Is something already listening on 127.0.0.1:<port> locally - checked
    with the facility that is actually reachable on each platform (`ss` on
    Linux, `netstat` on Windows, since ss is not shipped there)."""
    if WINDOWS:
        rc, out, _ = run(["netstat", "-ano", "-p", "TCP"], timeout=10)
        if rc != 0:
            return False
        needle = f"127.0.0.1:{port} "
        return any(needle in line and "LISTENING" in line for line in out.splitlines())
    rc, out, _ = run(["ss", "-ltn"], timeout=10)
    if rc != 0:
        return False
    return f"127.0.0.1:{port} " in out


def focused_workspace() -> Tuple[bool, Optional[str]]:
    """Return (sway_available, focused workspace name).

    Availability means swaymsg can query this compositor, not merely that the
    executable happens to be installed.
    """
    if not shutil.which("swaymsg"):
        return False, None
    rc, out, _ = run(["swaymsg", "-t", "get_workspaces"], timeout=5)
    if rc != 0 or not out:
        return False, None
    import json as _json
    try:
        workspaces = _json.loads(out)
    except ValueError:
        return False, None
    for workspace in workspaces:
        if workspace.get("focused"):
            return True, str(workspace.get("name"))
    return True, None


def place_on_workspace(pid: int, workspace: str) -> Optional[str]:
    """sway-only window placement. Returns the workspace name the window
    ended up on, or None if there is no sway to ask (swaymsg not on PATH -
    always true on Windows, so this is naturally a no-op there rather than a
    special-cased platform branch). This is deliberately the ONE piece of
    rfb_view.py/vm_view.py that is NOT part of the portable tunnel/viewer
    contract - see rfb_view.py's module docstring for why it is split out."""
    if not shutil.which("swaymsg"):
        return None
    escaped = workspace.replace("\\", "\\\\").replace('"', '\\"')
    move_rc, _, _ = run(
        ["swaymsg", f'[pid={pid}] move container to workspace "{escaped}"'], timeout=5
    )
    if move_rc != 0:
        return None
    rc, out, _ = run(["swaymsg", "-t", "get_tree"], timeout=5)
    if rc != 0 or not out:
        return None
    import json as _json

    def walk(node, ws=None):
        if node.get("type") == "workspace":
            ws = node["name"]
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            found = walk(child, ws)
            if found:
                return found
        return ws if node.get("pid") == pid else None

    try:
        placed = walk(_json.loads(out))
    except ValueError:
        return None
    return placed if placed == workspace else None


def focus_window(pid: int) -> bool:
    """Focus a Sway window by PID, making its workspace visible."""
    if not shutil.which("swaymsg"):
        return False
    rc, _, _ = run(["swaymsg", f"[pid={pid}] focus"], timeout=5)
    return rc == 0


def start_background(argv: Sequence[str], log_path: Path):
    """Start argv detached from this process's controlling terminal/console,
    with stdout/stderr redirected to log_path. setsid is POSIX-only, so this
    branches; Popen with no special flags is enough on both platforms to let
    the viewer keep running after this script exits, since neither platform
    needs the parent to stay alive for the child's session/console to
    persist here (unlike, say, a tmux pane)."""
    log_fh = open(log_path, "wb")
    kwargs = {}
    if WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(list(argv), stdout=log_fh, stderr=subprocess.STDOUT, **kwargs)


def pid_alive(pid: int) -> bool:
    if WINDOWS:
        rc, out, _ = run(["tasklist", "/fi", f"PID eq {pid}", "/nh"], timeout=10)
        return rc == 0 and str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def local_port_owner_pid(port: int) -> Optional[int]:
    """Which PID owns 127.0.0.1:<port> right now, if anything - used to
    verify what a listening local port actually IS before treating it as
    "our tunnel is already up" (never assume that from the port number
    alone)."""
    if WINDOWS:
        rc, out, _ = run(["netstat", "-ano", "-p", "TCP"], timeout=10)
        if rc != 0:
            return None
        needle = f"127.0.0.1:{port} "
        for line in out.splitlines():
            if needle in line and "LISTENING" in line:
                parts = line.split()
                if parts and parts[-1].isdigit():
                    return int(parts[-1])
        return None
    rc, out, _ = run(["ss", "-ltnp"], timeout=10)
    if rc != 0:
        return None
    needle = f"127.0.0.1:{port} "
    for line in out.splitlines():
        if needle not in line:
            continue
        m = None
        for tok in line.split():
            if tok.startswith("pid=") or ",pid=" in tok:
                for piece in tok.replace(")", "").split(","):
                    if piece.startswith("pid="):
                        m = piece[len("pid="):]
        if m and m.isdigit():
            return int(m)
    return None


def process_cmdline(pid: int) -> str:
    """The full command line a PID was started with - the only reliable
    way to tell whether a listener on our chosen local port is really an
    ssh tunnel to the host we expect, rather than something else (or a
    stale tunnel to a different host) that just happens to occupy the same
    port number."""
    if WINDOWS:
        rc, out, _ = run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            timeout=10,
        )
        return out.strip() if rc == 0 else ""
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode(
            CONSOLE_ENCODING, errors="replace"
        ).replace("\x00", " ").strip()
    except OSError:
        return ""
