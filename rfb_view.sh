#!/usr/bin/env bash
# View a remote desktop with librfb's own viewer, rfb_window_demo.
#
# Nothing here is specific to one machine. The RFB port is discovered from the
# remote host at run time (by asking which port its rfb_server is listening on),
# because it changes whenever that server is restarted. When the server is bound
# to loopback - which is the sane default, since RFB is not encrypted - an SSH
# tunnel is opened for it automatically.
#
# Usage: rfb_view.sh [-w WORKSPACE] [-p PORT] [-g DRM_NODE] [-e ENCODINGS]
#                    [--view-only] HOST [WORKSPACE]
#
# Keyboard and pointer are passed through; --view-only makes the window a
# read-only display instead.
#
# Exit codes: 2 usage, 3 no viewer binary, 4 host unreachable,
#             5 no rfb_server found on the host, 6 tunnel failed,
#             7 viewer died on startup.

set -u

self="${0##*/}"
WORKSPACE="${RFB_VIEW_WORKSPACE:-3}"
PORT="${RFB_VIEW_PORT:-}"
GPU="${RFB_VIEW_GPU:-}"
ENCODINGS="${RFB_VIEW_ENCODINGS:-zrle,raw}"
VIEWER="${RFB_WINDOW_DEMO:-rfb_window_demo}"
VIEW_ONLY="${RFB_VIEW_READONLY:-0}"

die() { printf '%s: %s\n' "$self" "$*" >&2; exit "${2:-1}"; }
usage() { sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }

while [ $# -gt 0 ]; do
	case "$1" in
		-w|--workspace) [ $# -ge 2 ] || die "--workspace needs a value" 2
			WORKSPACE="$2"; shift 2 ;;
		-p|--port) [ $# -ge 2 ] || die "--port needs a value" 2
			PORT="$2"; shift 2 ;;
		-g|--gpu) [ $# -ge 2 ] || die "--gpu needs a DRM node" 2
			GPU="$2"; shift 2 ;;
		-e|--encodings) [ $# -ge 2 ] || die "--encodings needs a value" 2
			ENCODINGS="$2"; shift 2 ;;
		--view-only) VIEW_ONLY=1; shift ;;
		-h|--help) usage 0 ;;
		--) shift; break ;;
		-*) die "unknown option '$1'" 2 ;;
		*) break ;;
	esac
done

[ $# -ge 1 ] || usage 2
HOST="$1"; shift
[ $# -ge 1 ] && { WORKSPACE="$1"; shift; }
[ $# -eq 0 ] || die "unexpected argument '$1'" 2

command -v "$VIEWER" >/dev/null 2>&1 ||
	die "$VIEWER not found on PATH. It is built from the librfb project; add its
       build output directory to PATH, e.g.
           add_path /mnt/build/librfb_build/librfb" 3

# rfb_window_demo renders through DRM/amdgpu, and its built-in default is an
# empty path, so a node must always be named explicitly.
if [ -z "$GPU" ]; then
	for node in /dev/dri/renderD*; do
		[ -e "$node" ] && { GPU="$node"; break; }
	done
fi
[ -n "$GPU" ] || die "no DRM render node found in /dev/dri; pass --gpu" 3

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=8)

remote_listeners() {
	# No quoting games: `tasklist` and `netstat` are parsed here instead of
	# running a PowerShell one-liner through the remote cmd.exe.
	local pids
	pids="$(timeout 30 ssh "${ssh_opts[@]}" "$HOST" tasklist /nh 2>/dev/null |
		tr -d '\r' | awk '$1 ~ /^rfb_server(\.exe)?$/ { print $2 }')"
	if [ -n "$pids" ]; then
		timeout 30 ssh "${ssh_opts[@]}" "$HOST" netstat -ano -p tcp 2>/dev/null |
			tr -d '\r' | awk -v pids="$pids" '
				BEGIN { split(pids, a); for (i in a) want[a[i]] = 1 }
				/LISTENING/ && ($5 in want) {
					n = split($2, hp, ":")
					addr = $2; sub(":" hp[n] "$", "", addr)
					print addr, hp[n]
				}'
		return
	fi
	# POSIX host fallback.
	timeout 30 ssh "${ssh_opts[@]}" "$HOST" \
		"ss -ltnp 2>/dev/null | grep rfb_server" 2>/dev/null |
		sed -n 's/.*LISTEN[^:]*\s\([0-9.:]*\):\([0-9]\+\)\s.*/\1 \2/p'
}

timeout 20 ssh "${ssh_opts[@]}" "$HOST" exit >/dev/null 2>&1 ||
	die "cannot ssh to $HOST - is it up, and is your key installed?" 4

listen_addr=""
if [ -z "$PORT" ]; then
	line="$(remote_listeners | head -n 1)"
	[ -n "$line" ] ||
		die "no listening rfb_server found on $HOST. Start it there (inside the
       interactive session, not a session-0 SSH shell), e.g.
           C:\\librfb\\rfb_server.exe --port 5901 --listen 127.0.0.1" 5
	read -r listen_addr PORT <<<"$line"
fi
printf '%s: %s rfb_server on %s:%s\n' "$self" "$HOST" "${listen_addr:-?}" "$PORT"

# Loopback, or unknown, means the port cannot be reached across the network, so
# forward it. RFB carries no encryption, so tunnelling is the right default even
# when the server does listen widely.
target_host=127.0.0.1
target_port="$PORT"
case "$listen_addr" in
	127.0.0.1|::1|"")
		local_port="${RFB_VIEW_LOCAL_PORT:-$((PORT + 10000))}"
		[ "$local_port" -gt 65535 ] 2>/dev/null && local_port=$((PORT + 1))
		if ss -ltn 2>/dev/null | grep -q "127.0.0.1:$local_port "; then
			printf '%s: reusing the tunnel already on 127.0.0.1:%s\n' "$self" "$local_port"
		else
			setsid ssh -N "${ssh_opts[@]}" -o ExitOnForwardFailure=yes \
				-o ServerAliveInterval=15 \
				-L "$local_port:127.0.0.1:$PORT" "$HOST" \
				>"${XDG_RUNTIME_DIR:-/tmp}/rfb_view-$HOST-tunnel.log" 2>&1 &
			tunnel=$!
			for _ in $(seq 1 20); do
				sleep 0.5
				ss -ltn 2>/dev/null | grep -q "127.0.0.1:$local_port " && break
			done
			ss -ltn 2>/dev/null | grep -q "127.0.0.1:$local_port " ||
				die "could not forward $HOST:$PORT to 127.0.0.1:$local_port" 6
			printf '%s: tunnel 127.0.0.1:%s -> %s:%s (pid %s)\n' \
				"$self" "$local_port" "$HOST" "$PORT" "$tunnel"
		fi
		target_port="$local_port"
		;;
	*) target_host="$listen_addr" ;;
esac

set -- "$VIEWER" "$target_host" "$target_port" "$ENCODINGS" --gpu "$GPU"
[ "$VIEW_ONLY" = 1 ] && set -- "$@" --view-only

log="${XDG_RUNTIME_DIR:-/tmp}/rfb_view-$HOST.log"
setsid "$@" >"$log" 2>&1 &
pid=$!
printf '%s: %s\n' "$self" "$*"

placed=""
for _ in $(seq 1 40); do
	sleep 0.5
	kill -0 "$pid" 2>/dev/null ||
		die "viewer exited during startup; see $log
       (it has crashed on a bad DRM node before - try --gpu /dev/dri/renderD128)" 7
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
