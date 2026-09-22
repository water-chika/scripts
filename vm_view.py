#!/usr/bin/env python3
"""vm_view.py - port of vm_view.sh: open a viewer on a libvirt domain's
console and place it on a workspace.

Same split as rfb_view.py: libvirt discovery (virsh domstate/dumpxml,
XML parsing) and viewer selection are the portable part - virsh and
virt-viewer both ship Windows builds, so a colleague with libvirt tools
installed on Windows gets the same discovery logic unchanged. sway
placement is skipped wherever swaymsg is not on PATH (always true on
Windows).

Usage matches vm_view.sh:
  vm_view.py [-w WORKSPACE] [-c URI] [-e ENCODINGS] [--view-only] DOMAIN [WORKSPACE]

Strictly read-only: never starts, stops, resets or reconfigures a domain.

Exit codes match vm_view.sh: 2 usage, 3 libvirt/domain problem,
4 domain not running, 5 no usable viewer, 6 viewer died on startup.
"""

from __future__ import annotations

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

import _common as sh


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False, usage="vm_view.py [-w WORKSPACE] [-c URI] [-e ENCODINGS] [--view-only] DOMAIN [WORKSPACE]")
    p.add_argument("-w", "--workspace", default="3")
    p.add_argument("-c", "--connect", default="qemu:///system")
    p.add_argument("-e", "--encodings", default="h264,zrle,raw")
    p.add_argument("--view-only", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    p.add_argument("domain", nargs="?")
    p.add_argument("workspace_pos", nargs="?")
    ns = p.parse_args(argv)
    if ns.help:
        print(__doc__)
        raise SystemExit(0)
    if not ns.domain:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    if ns.workspace_pos:
        ns.workspace = ns.workspace_pos
    return ns


def parse_graphics(xml_text: str) -> Tuple[str, str, str]:
    """Same XML walk vm_view.sh's python3 -c one-liner did: returns
    (type, port, addr), with addr == "" meaning "no TCP endpoint" (a
    listen type='none' console, or no graphics device at all -> type
    'none')."""
    root = ET.fromstring(xml_text)
    g = root.find("./devices/graphics")
    if g is None:
        return "none", "0", ""
    listen = g.find("listen")
    addr = g.get("listen") or (listen.get("address") if listen is not None else "") or ""
    if listen is not None and listen.get("type") == "none":
        addr = ""
    return g.get("type") or "none", g.get("port") or "0", addr


def main(argv: Optional[List[str]] = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    domain = ns.domain

    sh.which_or_die("virsh", "install libvirt to talk to the hypervisor", exit_code=3)

    rc, out, err = sh.run(["virsh", "--connect", ns.connect, "domstate", domain], timeout=20)
    if rc != 0:
        sh.die(f"cannot reach libvirt at {ns.connect}, or no domain '{domain}': {(out + err).strip()}", 3)
    state = out.strip()
    if state != "running":
        sh.die(
            f"domain '{domain}' is {state}, not running. Refusing to start it - a "
            f"build may be in progress. Start it yourself if you mean to: "
            f"virsh --connect {ns.connect} start {domain}",
            4,
        )

    rc, xml_out, _ = sh.run(["virsh", "--connect", ns.connect, "dumpxml", domain], timeout=20)
    if rc != 0:
        sh.die(f"could not read the domain XML for '{domain}'", 3)
    try:
        gtype, gport, gaddr = parse_graphics(xml_out)
    except ET.ParseError:
        sh.die(f"could not parse the graphics device out of the domain XML", 3)
    if gtype == "none":
        sh.die(f"domain '{domain}' has no graphics device to view", 3)
    listen_addr = "127.0.0.1" if gaddr in ("0.0.0.0", "::", "") else gaddr

    viewer_argv: List[str] = []
    endpoint = ""
    viewer_name = ""
    import shutil as _shutil

    if gtype == "vnc" and gport.isdigit() and int(gport) > 0 and gaddr:
        rfb = _shutil.which("rfb_window_demo")
        if rfb:
            viewer_name = "rfb_window_demo"
            viewer_argv = [rfb, listen_addr, gport, ns.encodings]
            if ns.view_only:
                viewer_argv.append("--view-only")
            endpoint = f"{listen_addr}:{gport}"
    if not viewer_name:
        vv = _shutil.which("virt-viewer")
        if vv:
            viewer_name = "virt-viewer"
            viewer_argv = [vv, "--connect", ns.connect, "--attach", domain]
            endpoint = "libvirt fd"

    if not viewer_name:
        sh.die(
            f"no usable viewer for a '{gtype}' console. Install virt-viewer, or "
            "put rfb_window_demo on PATH for a VNC console",
            5,
        )

    print(f"vm_view: {gtype} console ({endpoint}) via {viewer_name}")

    log = sh.runtime_dir() / f"vm_view-{domain}.log"
    proc = sh.start_background(viewer_argv, log)

    placed = None
    for _ in range(40):
        time.sleep(0.5)
        if not sh.pid_alive(proc.pid):
            sh.die(f"viewer exited during startup; see {log}", 6)
        placed = sh.place_on_workspace(proc.pid, ns.workspace)
        if placed:
            break

    if placed:
        print(f"vm_view: window (pid {proc.pid}) is on workspace {placed}")
        if placed != ns.workspace:
            print(f"vm_view: warning - asked for workspace {ns.workspace}", file=sys.stderr)
    else:
        print(
            f"vm_view: viewer running as pid {proc.pid}, placement unconfirmed "
            "(no sway - normal on Windows, place the window yourself)",
            file=sys.stderr,
        )
    print(f"vm_view: log {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
