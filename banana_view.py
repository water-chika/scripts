#!/usr/bin/env python3
"""banana_view.py - port of banana_view.sh: view the water-banana machine
(the Windows 11 guest running as the libvirt domain 'win11' on apple.water,
the only XGL build host).

This file is only the machine; the generic parts live in rfb_view.py and
vm_view.py, ported in the same commit. Preferred route is librfb's
rfb_window_demo against the rfb_server already running inside the guest
session (rfb_view.py tunnels it over SSH). If that is not answering, fall
back to the hypervisor's SPICE console via vm_view.py, which survives
guest-side trouble but is read-only viewing, not an RFB session.

VIEW ONLY. Never power-cycle this VM: a build may be running. The one and
only recovery is `virsh --connect qemu:///system start win11`, never IPMI.

Usage: banana_view.py [workspace]     (defaults to the focused Sway workspace)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

import rfb_view
import vm_view

SCRIPT_DIR = Path(__file__).resolve().parent


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    workspace = args[0] if args else None
    if workspace is None:
        _, focused = rfb_view.common.focused_workspace()
        workspace = focused
    host = os.environ.get("BANANA_HOST", "water-banana")
    domain = os.environ.get("BANANA_DOMAIN", "win11")

    try:
        return rfb_view.main([host] + ([workspace] if workspace else []))
    except SystemExit as e:
        if e.code == 0:
            return 0

    print("banana_view: librfb route failed, falling back to the SPICE console", file=sys.stderr)
    return vm_view.main([domain] + ([workspace] if workspace else []))


if __name__ == "__main__":
    raise SystemExit(main())
