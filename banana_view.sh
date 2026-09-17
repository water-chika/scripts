#!/usr/bin/env bash
# water-banana: the Windows 11 guest running as the libvirt domain 'win11' on
# apple.water, and the only XGL build host. This file is only the machine; the
# generic parts live in rfb_view.sh and vm_view.sh.
#
# Usage: banana_view.sh [workspace]     (workspace defaults to 3)
#
# Preferred route is water-chika's own viewer, librfb's rfb_window_demo, against
# the rfb_server already running inside the guest session. That server listens on
# loopback, so rfb_view.sh tunnels it over SSH. If the guest server is not
# answering, fall back to the hypervisor console, which survives guest-side
# trouble but is SPICE - no RFB client can attach to it.
#
# VIEW ONLY. Never power-cycle this VM: a build may be running. The one and only
# recovery is `virsh --connect qemu:///system start win11`, never IPMI.

set -u
dir="$(dirname "$(readlink -f "$0")")"

if "$dir/rfb_view.sh" "${BANANA_HOST:-water-banana}" "${1:-3}"; then
	exit 0
fi

printf 'banana_view: librfb route failed, falling back to the SPICE console\n' >&2
exec "$dir/vm_view.sh" "${BANANA_DOMAIN:-win11}" "${1:-3}"
