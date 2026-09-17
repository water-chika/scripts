#!/usr/bin/env bash
# Open a viewer window on the console of a libvirt domain, and put it on a
# workspace. Nothing here is specific to one machine: the protocol, port and
# listen address are discovered from libvirt every run, because they change
# when the VM restarts.
#
# Strictly read-only. This script never starts, stops, resets or reconfigures a
# domain. If the VM is down it says so and exits nonzero - a build may be in
# progress, and only a human should decide to start it.
#
# Usage: vm_view.sh [-w WORKSPACE] [-c URI] [-e ENCODINGS] [--view-only] DOMAIN
#
# Viewer choice, by what libvirt reports:
#   vnc with a TCP port -> rfb_window_demo (librfb), else virt-viewer
#   spice, or a console with listen type='none' -> virt-viewer --attach
#     (there is no TCP endpoint in that case; the console is reached over an fd
#      libvirt passes to the client, so an RFB client cannot be used)
#
# Exit codes: 2 usage, 3 libvirt/domain problem, 4 domain not running,
#             5 no usable viewer, 6 viewer died on startup.

set -u

URI="${VM_VIEW_URI:-qemu:///system}"
WORKSPACE="${VM_VIEW_WORKSPACE:-3}"
RFB_WINDOW_DEMO="${RFB_WINDOW_DEMO:-rfb_window_demo}"
RFB_ENCODINGS="${VM_VIEW_ENCODINGS:-h264,zrle,raw}"
VIEW_ONLY="${VM_VIEW_READONLY:-0}"

self="${0##*/}"
die() { printf '%s: %s\n' "$self" "$*" >&2; exit "${2:-1}"; }
usage() {
	sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
	exit "${1:-2}"
}

while [ $# -gt 0 ]; do
	case "$1" in
		-w|--workspace) [ $# -ge 2 ] || die "--workspace needs a value" 2
			WORKSPACE="$2"; shift 2 ;;
		-c|--connect) [ $# -ge 2 ] || die "--connect needs a URI" 2
			URI="$2"; shift 2 ;;
		-e|--encodings) [ $# -ge 2 ] || die "--encodings needs a value" 2
			RFB_ENCODINGS="$2"; shift 2 ;;
		--view-only) VIEW_ONLY=1; shift ;;
		-h|--help) usage 0 ;;
		--) shift; break ;;
		-*) die "unknown option '$1'" 2 ;;
		*) break ;;
	esac
done

[ $# -ge 1 ] || usage 2
DOMAIN="$1"; shift
# Second positional is the workspace, so `vm_view.sh win11 3` reads naturally.
[ $# -ge 1 ] && { WORKSPACE="$1"; shift; }
[ $# -eq 0 ] || die "unexpected argument '$1'" 2

command -v virsh >/dev/null 2>&1 ||
	die "virsh not found - install libvirt to talk to the hypervisor" 3

state="$(virsh --connect "$URI" domstate "$DOMAIN" 2>&1)" ||
	die "cannot reach libvirt at $URI, or no domain '$DOMAIN': $state" 3

if [ "$state" != running ]; then
	die "domain '$DOMAIN' is $state, not running. Refusing to start it - a build
       may be in progress. Start it yourself if you mean to:
           virsh --connect $URI start $DOMAIN" 4
fi

xml="$(virsh --connect "$URI" dumpxml "$DOMAIN")" ||
	die "could not read the domain XML for '$DOMAIN'" 3

graphics="$(printf '%s' "$xml" | python3 -c '
import sys, xml.etree.ElementTree as ET
g = ET.fromstring(sys.stdin.read()).find("./devices/graphics")
if g is None:
    print("none 0 -")
    sys.exit(0)
listen = g.find("listen")
addr = g.get("listen") or (listen is not None and listen.get("address")) or ""
if listen is not None and listen.get("type") == "none":
    addr = ""
print(g.get("type") or "none", g.get("port") or "0", addr or "-")
')" || die "could not parse the graphics device out of the domain XML" 3

read -r gtype gport gaddr <<<"$graphics"
[ "$gtype" = none ] && die "domain '$DOMAIN' has no graphics device to view" 3
[ "$gaddr" = - ] && gaddr=""
case "$gaddr" in 0.0.0.0|::|"") listen_addr=127.0.0.1 ;; *) listen_addr="$gaddr" ;; esac

viewer=""
if [ "$gtype" = vnc ] && [ "${gport:-0}" -gt 0 ] 2>/dev/null && [ -n "$gaddr" ]; then
	# A real RFB endpoint: water-chika's own viewer can drive it directly.
	if command -v "$RFB_WINDOW_DEMO" >/dev/null 2>&1; then
		viewer="$RFB_WINDOW_DEMO"
		set -- "$RFB_WINDOW_DEMO" "$listen_addr" "$gport" "$RFB_ENCODINGS"
		[ "$VIEW_ONLY" = 1 ] && set -- "$@" --view-only
		endpoint="$listen_addr:$gport"
	fi
fi
if [ -z "$viewer" ] && command -v virt-viewer >/dev/null 2>&1; then
	viewer=virt-viewer
	set -- virt-viewer --connect "$URI" --attach "$DOMAIN"
	endpoint="libvirt fd"
fi

if [ -z "$viewer" ]; then
	die "no usable viewer for a '$gtype' console. Install virt-viewer
       (pacman -S virt-viewer), or put $RFB_WINDOW_DEMO on PATH for a VNC
       console" 5
fi

printf '%s: %s console (%s) via %s\n' "$self" "$gtype" "$endpoint" "$viewer"

log="${XDG_RUNTIME_DIR:-/tmp}/vm_view-$DOMAIN.log"
setsid "$@" >"$log" 2>&1 &
pid=$!

placed=""
for _ in $(seq 1 40); do
	sleep 0.5
	kill -0 "$pid" 2>/dev/null ||
		die "viewer exited during startup; see $log" 6
	command -v swaymsg >/dev/null 2>&1 || break
	swaymsg "[pid=$pid] move container to workspace $WORKSPACE" >/dev/null 2>&1
	placed="$(swaymsg -t get_tree 2>/dev/null | PID="$pid" python3 -c '
import json, os, sys
pid = int(os.environ["PID"])
def walk(n, ws=None):
    if n.get("type") == "workspace":
        ws = n["name"]
    for c in n.get("nodes", []) + n.get("floating_nodes", []):
        r = walk(c, ws)
        if r:
            return r
    return ws if n.get("pid") == pid else None
print(walk(json.load(sys.stdin)) or "")
')"
	[ -n "$placed" ] && break
done

if [ -n "$placed" ]; then
	printf '%s: window (pid %s) is on workspace %s\n' "$self" "$pid" "$placed"
	[ "$placed" = "$WORKSPACE" ] ||
		printf '%s: warning - asked for workspace %s\n' "$self" "$WORKSPACE" >&2
else
	printf '%s: viewer running as pid %s, placement unconfirmed (no sway?)\n' \
		"$self" "$pid" >&2
fi
printf '%s: log %s\n' "$self" "$log"
