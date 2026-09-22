#!/usr/bin/env python3
"""rfb_view.py - port of rfb_view.sh: view a remote desktop with librfb's own
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

Usage matches rfb_view.sh:
  rfb_view.py [-w WORKSPACE] [-p PORT] [-g DRM_NODE] [-e ENCODINGS]
              [--view-only] HOST [WORKSPACE]

--gpu/DRM discovery is Linux-only (rfb_window_demo renders through
DRM/amdgpu); on Windows there is no /dev/dri, so --gpu is simply not
required there - this is the other genuine platform difference besides sway.

Exit codes match rfb_view.sh: 2 usage, 3 no viewer binary, 4 host
unreachable, 5 no rfb_server found on the host, 6 tunnel failed, 7 viewer
died on startup.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import _common as sh


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False, usage="rfb_view.py [-w WORKSPACE] [-p PORT] [-g DRM_NODE] [-e ENCODINGS] [--view-only] HOST [WORKSPACE]")
    p.add_argument("-w", "--workspace", default="3")
    p.add_argument("-p", "--port", type=int, default=None)
    p.add_argument("-g", "--gpu", default=None)
    p.add_argument("-e", "--encodings", default="zrle,raw")
    p.add_argument("--view-only", action="store_true")
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
    """Same two-pass parse rfb_view.sh's Windows branch does: find
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
    """Same as rfb_view.sh's POSIX fallback: `ss -ltnp | grep rfb_server`,
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
    rc, out, _ = sh.run(sh.ssh_argv(host, ["tasklist", "/nh"]), timeout=30)
    if rc == 0 and out:
        rc2, netout, _ = sh.run(sh.ssh_argv(host, ["netstat", "-ano", "-p", "tcp"]), timeout=30)
        found = parse_windows_listeners(out, netout if rc2 == 0 else "")
        if found:
            return found[0]
    rc, out, _ = sh.run(sh.ssh_argv(host, ["ss -ltnp 2>/dev/null | grep rfb_server"]), timeout=30)
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
                        port_listening, port_owner_cmdline, start: int = 15901) -> Tuple[int, bool]:
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
    candidate = port_map.get(host)
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
        port = start
        while port in used_ports or port_listening(port):
            port += 1
        candidate = port
    port_map[host] = candidate
    return candidate, False


def main(argv: Optional[List[str]] = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    host = ns.host

    viewer = sh.which_or_die(
        "rfb_window_demo",
        "It is built from the librfb project; add its build output directory "
        "to PATH, e.g. add_path /mnt/build/librfb_build/librfb",
        exit_code=3,
    )

    gpu = ns.gpu
    if not gpu and not sh.WINDOWS:
        gpu = find_gpu_node()
        if not gpu:
            sh.die("no DRM render node found in /dev/dri; pass --gpu", 3)

    rc, _, _ = sh.run(sh.ssh_argv(host, ["exit"]), timeout=20)
    if rc != 0:
        sh.die(f"cannot ssh to {host} - is it up, and is your key installed?", 4)

    port = str(ns.port) if ns.port else None
    listen_addr = ""
    if not port:
        found = discover_listener(host)
        if not found:
            sh.die(
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
        port_map_path = sh.runtime_dir() / "rfb_view-ports.json"
        port_map = load_port_map(port_map_path)
        local_port, reused = resolve_local_port(
            host, port, port_map,
            port_listening=sh.local_port_listening,
            port_owner_cmdline=lambda p: (
                sh.process_cmdline(sh.local_port_owner_pid(p))
                if sh.local_port_owner_pid(p) is not None else ""
            ),
        )
        save_port_map(port_map_path, port_map)
        if reused:
            print(f"rfb_view: reusing the tunnel already on 127.0.0.1:{local_port} -> {host}:{port}")
        else:
            tunnel_log = sh.runtime_dir() / f"rfb_view-{host}-tunnel.log"
            tunnel_argv = [
                "ssh", "-N", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
                "-L", f"{local_port}:127.0.0.1:{port}", host,
            ]
            proc = sh.start_background(tunnel_argv, tunnel_log)
            up = False
            for _ in range(20):
                time.sleep(0.5)
                if sh.local_port_listening(local_port):
                    up = True
                    break
            if not up:
                sh.die(f"could not forward {host}:{port} to 127.0.0.1:{local_port}", 6)
            print(f"rfb_view: tunnel 127.0.0.1:{local_port} -> {host}:{port} (pid {proc.pid})")
        target_port = str(local_port)
    else:
        target_host = listen_addr

    viewer_argv = [viewer, target_host, target_port, ns.encodings]
    if gpu:
        viewer_argv += ["--gpu", gpu]
    if ns.view_only:
        viewer_argv.append("--view-only")

    log = sh.runtime_dir() / f"rfb_view-{host}.log"
    proc = sh.start_background(viewer_argv, log)
    print("rfb_view: " + " ".join(viewer_argv))

    placed = None
    for _ in range(40):
        time.sleep(0.5)
        if not sh.pid_alive(proc.pid):
            sh.die(
                f"viewer exited during startup; see {log} (it has crashed on a "
                "bad DRM node before - try --gpu /dev/dri/renderD128)",
                7,
            )
        placed = sh.place_on_workspace(proc.pid, ns.workspace)
        if placed:
            break

    if placed:
        print(f"rfb_view: window (pid {proc.pid}) is on workspace {placed}")
        if placed != ns.workspace:
            print(f"rfb_view: warning - asked for workspace {ns.workspace}", file=sys.stderr)
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
