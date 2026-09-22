#!/usr/bin/env python3
"""add_path.py - port of add_path.sh's `add_path` shell function: prepend a
directory to PATH without duplicating it.

Same caveat as ssh_agent.py: a subprocess cannot mutate its parent shell's
environment, so this prints an eval-able assignment line rather than
pretending to change PATH in place. The de-duplication logic itself is the
genuinely portable part and is plain string/list handling here - no shell
involved at all, so it is exercised directly by unit tests with no
subprocess.

Usage:
  eval "$(python3 add_path.py /mnt/build/librfb_build/librfb)"        # bash/zsh
  Invoke-Expression (python3 add_path.py --shell powershell C:\tools | Out-String)  # PowerShell
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

import _common as sh


def add_path(current: str, new_dir: str, sep: str = os.pathsep) -> str:
    """Prepend new_dir to current unless it is already present. Mirrors
    add_path.sh's `case ":${PATH}:" in *:"$1":*)` check but works on
    os.pathsep (";" on Windows, ":" on POSIX) instead of assuming ":"."""
    parts = current.split(sep) if current else []
    if new_dir in parts:
        return current
    return new_dir if not current else f"{new_dir}{sep}{current}"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--shell", choices=["posix", "powershell"],
                    default="powershell" if sh.WINDOWS else "posix")
    p.add_argument("directory")
    ns = p.parse_args(sys.argv[1:] if argv is None else argv)

    new_path = add_path(os.environ.get("PATH", ""), ns.directory)
    if ns.shell == "powershell":
        print(f'$env:PATH = "{new_path}"')
    else:
        print(f'export PATH="{new_path}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
