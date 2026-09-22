#!/usr/bin/env python3
"""ssh_agent.py - port of ssh-agent.sh: point SSH_AUTH_SOCK at a per-user
agent, starting one if needed.

ssh-agent.sh was meant to be *sourced* (`source ssh-agent.sh`) so it could
export SSH_AUTH_SOCK into the calling interactive shell. A subprocess -
Python included - can never modify its parent shell's environment, so this
script keeps the same contract real `ssh-agent -s` uses: it prints
shell-eval-able assignment lines on stdout, and the caller does the
`eval "$(...)"` (or the PowerShell equivalent). That is the only way this
was ever going to be portable, since env-mutation-of-the-caller is not a
process-boundary-safe operation on either platform.

Usage:
  eval "$(python3 ssh_agent.py)"                       # bash/zsh
  Invoke-Expression (python3 ssh_agent.py --shell powershell | Out-String)  # PowerShell

--shell defaults to powershell on Windows, posix otherwise; pass it
explicitly to override.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

import _common as sh


def agent_socket_path() -> Path:
    user = os.environ.get("USERNAME" if sh.WINDOWS else "USER", "user")
    if sh.WINDOWS:
        # OpenSSH for Windows' ssh-agent is a named-pipe service, not a
        # filesystem socket the -a flag can point at the way POSIX ssh-agent
        # works; \\.\pipe\openssh-ssh-agent is the fixed, well-known pipe
        # name it always uses, so there is nothing to "point at" per user.
        return Path(r"\\.\pipe\openssh-ssh-agent")
    return sh.runtime_dir() / f"ssh-agent-{user}"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--shell", choices=["posix", "powershell"],
                    default="powershell" if sh.WINDOWS else "posix")
    ns = p.parse_args(sys.argv[1:] if argv is None else argv)

    sock = agent_socket_path()

    if sh.WINDOWS:
        # The service (or a per-session ssh-agent) either already owns the
        # pipe or it does not; this script does not attempt to start a
        # Windows service (that needs an elevated `Set-Service` one-time
        # step documented in the README, not a per-shell script).
        if ns.shell == "powershell":
            print(f'$env:SSH_AUTH_SOCK = "{sock}"')
        else:
            print(f'export SSH_AUTH_SOCK="{sock}"')
        return 0

    if not sock.exists():
        rc, out, err = sh.run(["ssh-agent", "-a", str(sock)], timeout=10)
        if rc != 0:
            sh.die(f"ssh-agent -a {sock} failed: {err.strip()}", 1)
    print(f'export SSH_AUTH_SOCK="{sock}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
