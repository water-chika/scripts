#!/usr/bin/env python3
"""rfb_view.py - port of the former shell implementation: view a remote desktop with librfb's own
viewer, rfb_window_demo.

Two concerns, kept deliberately separate (per the port brief): the tunnel and
port discovery are the portable part - they work the same on Linux and
Windows, since they only ever ssh OUT to the target and inspect ITS listening
sockets (the target's OS, Windows or POSIX, is unrelated to which OS this
script itself runs on). Window placement on a sway workspace is NOT portable:
it only exists because this machine's own desktop is sway. On Windows there is
no sway, so place_on_workspace() is a no-op there (swaymsg is not on PATH) -
this script still finds the port, opens the tunnel and starts the viewer, a
Windows colleague just also has to place the window by hand, exactly as they
would with any other viewer app.

Usage matches the former shell implementation:
  rfb_view.py [-w WORKSPACE] [-p PORT] [-g DRM_NODE] [-e ENCODINGS]
              [--view-only] HOST [WORKSPACE]

--gpu/DRM discovery is Linux-only (rfb_window_demo renders through
DRM/amdgpu); on Windows there is no /dev/dri, so --gpu is simply not
required there - this is the other genuine platform difference besides sway.

Exit codes match the former shell implementation: 2 usage, 3 no viewer binary, 4 host
unreachable, 5 no rfb_server found on the host, 6 tunnel failed, 7 viewer
died on startup.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import _common as common


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def _env_int(name: str) -> Optional[int]:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"{name} must be an integer, got {value!r}")


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False, usage="rfb_view.py [-w WORKSPACE] [-p PORT] [-g DRM_NODE] [-e ENCODINGS] [--view-only] HOST [WORKSPACE]")
    p.add_argument("-w", "--workspace", default=os.environ.get("RFB_VIEW_WORKSPACE"))
    p.add_argument("-p", "--port", type=int, default=_env_int("RFB_VIEW_PORT"))
    p.add_argument("-g", "--gpu", default=os.environ.get("RFB_VIEW_GPU"))
    p.add_argument("-e", "--encodings", default=os.environ.get("RFB_VIEW_ENCODINGS", "zrle,raw"))
    p.add_argument("--view-only", action="store_true", default=_env_bool("RFB_VIEW_READONLY"))
    p.add_argument("-h", "--help", action="store_true")
    p.add_argument("host", nargs="?")
    p.add_argument("workspace_pos", nargs="?")
    ns = p.parse_args(argv)
    if ns.help:
        print(__doc__)
        raise SystemExit(0)
    if not ns.host:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    if ns.workspace_pos:
        ns.workspace = ns.workspace_pos
    return ns


def parse_windows_listeners(tasklist_out: str, netstat_out: str) -> List[Tuple[str, str]]:
    """Same two-pass parse the former shell implementation's Windows branch does: find
    rfb_server's PID(s) via `tasklist`, then match them against `netstat
    -ano -p tcp` LISTENING lines. Returns a list of (addr, port)."""
    pids = set()
    for line in tasklist_out.splitlines():
        parts = line.split()
        if parts and parts[0].lower() in ("rfb_server", "rfb_server.exe"):
            if len(parts) > 1:
                pids.add(parts[1])
    if not pids:
        return []
    results = []
    for line in netstat_out.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr, pid = parts[1], parts[-1]
        if pid not in pids:
            continue
        addr, _, port = local_addr.rpartition(":")
        if addr and port:
            results.append((addr, port))
    return results


def parse_posix_listeners(ss_out: str) -> List[Tuple[str, str]]:
    """Same as the former shell implementation's POSIX fallback: `ss -ltnp | grep rfb_server`,
    parsed here instead of with a sed one-liner."""
    results = []
    for line in ss_out.splitlines():
        if "rfb_server" not in line:
            continue
        parts = line.split()
        for tok in parts:
            if tok.count(":") >= 1 and tok.rsplit(":", 1)[-1].isdigit():
                addr, _, port = tok.rpartition(":")
                results.append((addr, port))
                break
    return results


def discover_listener(host: str) -> Optional[Tuple[str, str]]:
    rc, out, _ = common.run(common.ssh_argv(host, ["tasklist", "/nh"]), timeout=30)
    if rc == 0 and out:
        rc2, netout, _ = common.run(common.ssh_argv(host, ["netstat", "-ano", "-p", "tcp"]), timeout=30)
        found = parse_windows_listeners(out, netout if rc2 == 0 else "")
        if found:
            return found[0]
    rc, out, _ = common.run(common.ssh_argv(host, ["ss -ltnp 2>/dev/null | grep rfb_server"]), timeout=30)
    found = parse_posix_listeners(out)
    if found:
        return found[0]
    return None


def find_gpu_node() -> Optional[str]:
    dri = Path("/dev/dri")
    if not dri.is_dir():
        return None
    for node in sorted(dri.glob("renderD*")):
        return str(node)
    return None


def load_port_map(path: Path) -> dict:
    """host -> local tunnel port, persisted so the SAME host reuses the
    SAME local port across separate invocations (deterministic, not
    random) while DIFFERENT hosts never collapse onto one shared port -
    that collapse is the bug this whole file exists to fix."""
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_port_map(path: Path, mapping: dict) -> None:
    import json
    try:
        path.write_text(json.dumps(mapping), encoding="utf-8")
    except OSError:
        pass  # best-effort persistence; a lost map just means a fresh port next run


def resolve_local_port(host: str, remote_port: str, port_map: dict, *,
                        port_listening, port_owner_cmdline, start: int = 15901,
                        preferred: Optional[int] = None) -> Tuple[int, bool]:
    """Decide which local port forwards host's remote_port, and whether an
    existing tunnel on it can be reused. port_map is host -> local_port,
    mutated in place. port_listening(port)->bool and
    port_owner_cmdline(port)->str are injected so this is testable with no
    real ssh/ss/netstat (see test_scripts_port.py).

    Reuse requires BOTH: the port recorded for THIS host is listening, AND
    the process on it is an ssh tunnel whose argv names this exact host
    and this exact remote port - never assumed from the port number alone,
    which is exactly what let water-coffee's viewer silently show
    water-banana's desktop.
    """
    used_ports = set(port_map.values())
    candidate = preferred if preferred is not None else port_map.get(host)
    if candidate is not None and port_listening(candidate):
        cmdline = port_owner_cmdline(candidate) or ""
        tokens = cmdline.split()
        if host in tokens and any(t.endswith(f":{remote_port}") for t in tokens):
            return candidate, True
        # Something else - or a stale tunnel to a different host/port - is
        # sitting on the port we last used for this host. Do not adopt it;
        # pick a fresh one below instead.
        used_ports.discard(candidate)
        candidate = None
    if candidate is None:
        port = preferred if preferred is not None else start
        while port in used_ports or port_listening(port):
            port += 1
        if port > 65535:
            raise RuntimeError(f"no free local TCP port at or above {start}")
        candidate = port
    port_map[host] = candidate
    return candidate, False


def main(argv: Optional[List[str]] = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    host = ns.host

    viewer_name = os.environ.get("RFB_WINDOW_DEMO", "rfb_window_demo")
    viewer = common.which_or_die(
        viewer_name,
        "It is built from the librfb project; add its build output directory "
        "to PATH, e.g. add_path /mnt/build/librfb_build/librfb",
        exit_code=3,
    )

    gpu = ns.gpu
    if not gpu and not common.WINDOWS:
        gpu = find_gpu_node()
        if not gpu:
            common.die("no DRM render node found in /dev/dri; pass --gpu", 3)

    rc, _, _ = common.run(common.ssh_argv(host, ["exit"]), timeout=20)
    if rc != 0:
        common.die(f"cannot ssh to {host} - is it up, and is your key installed?", 4)

    port = str(ns.port) if ns.port else None
    listen_addr = ""
    if not port:
        found = discover_listener(host)
        if not found:
            common.die(
                f"no listening rfb_server found on {host}. Start it there "
                "(inside the interactive session, not a session-0 SSH shell), e.g. "
                "C:\\librfb\\rfb_server.exe --port 5901 --listen 127.0.0.1",
                5,
            )
        listen_addr, port = found
    print(f"rfb_view: {host} rfb_server on {listen_addr or '?'}:{port}")

    target_host = "127.0.0.1"
    target_port = port
    if listen_addr in ("127.0.0.1", "::1", ""):
        port_map_path = common.runtime_dir() / "rfb_view-ports.json"
        port_map = load_port_map(port_map_path)
        local_port, reused = resolve_local_port(
            host, port, port_map,
            port_listening=common.local_port_listening,
            preferred=_env_int("RFB_VIEW_LOCAL_PORT"),
            port_owner_cmdline=lambda p: (
                common.process_cmdline(common.local_port_owner_pid(p))
                if common.local_port_owner_pid(p) is not None else ""
            ),
        )
        save_port_map(port_map_path, port_map)
        if reused:
            print(f"rfb_view: reusing the tunnel already on 127.0.0.1:{local_port} -> {host}:{port}")
        else:
            tunnel_log = common.runtime_dir() / f"rfb_view-{host}-tunnel.log"
            tunnel_argv = [
                "ssh", "-N", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
                "-L", f"{local_port}:127.0.0.1:{port}", host,
            ]
            proc = common.start_background(tunnel_argv, tunnel_log)
            up = False
            for _ in range(20):
                time.sleep(0.5)
                if common.local_port_listening(local_port):
                    up = True
                    break
            if not up:
                common.die(f"could not forward {host}:{port} to 127.0.0.1:{local_port}", 6)
            owner_pid = common.local_port_owner_pid(local_port)
            owner_cmdline = common.process_cmdline(owner_pid) if owner_pid is not None else ""
            owner_tokens = owner_cmdline.split()
            if host not in owner_tokens or not any(t.endswith(f":{port}") for t in owner_tokens):
                common.die(
                    f"local port {local_port} is listening but is not the requested "
                    f"SSH tunnel to {host}:{port}", 6)
            print(f"rfb_view: tunnel 127.0.0.1:{local_port} -> {host}:{port} (pid {proc.pid})")
        target_port = str(local_port)
    else:
        target_host = host if listen_addr in ("0.0.0.0", "::") else listen_addr

    viewer_argv = [viewer, target_host, target_port, ns.encodings]
    if gpu:
        viewer_argv += ["--gpu", gpu]
    if ns.view_only:
        viewer_argv.append("--view-only")

    log = common.runtime_dir() / f"rfb_view-{host}.log"
    proc = common.start_background(viewer_argv, log)
    print("rfb_view: " + " ".join(viewer_argv))

    sway_available, focused = common.focused_workspace()
    workspace = ns.workspace or focused or "3"
    placed = None
    if sway_available:
        for _ in range(40):
            time.sleep(0.5)
            if not common.pid_alive(proc.pid):
                common.die(
                    f"viewer exited during startup; see {log} (it has crashed on a "
                    "bad DRM node before - try --gpu /dev/dri/renderD128)",
                    7,
                )
            placed = common.place_on_workspace(proc.pid, workspace)
            if placed:
                break
        if not placed:
            common.die(f"viewer is running but no Sway window appeared within 20s; see {log}", 7)
    else:
        time.sleep(1)
        if not common.pid_alive(proc.pid):
            common.die(f"viewer exited during startup; see {log}", 7)

    if placed:
        focused_ok = common.focus_window(proc.pid)
        print(f"rfb_view: window (pid {proc.pid}) is on workspace {placed}")
        if not focused_ok:
            print("rfb_view: warning - window opened but could not be focused", file=sys.stderr)
        if placed != workspace:
            print(f"rfb_view: warning - asked for workspace {workspace}", file=sys.stderr)
    else:
        print(
            f"rfb_view: viewer running as pid {proc.pid}, placement unconfirmed "
            "(no sway - normal on Windows, place the window yourself)",
            file=sys.stderr,
        )
    print(f"rfb_view: log {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
