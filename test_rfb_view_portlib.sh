#!/usr/bin/env bash
# Offline regression test for rfb_view_portlib.sh - the per-host local
# tunnel port bookkeeping. Runs with NO real ssh/network access: `ss` is
# overridden as a shell function driven by two small tables (LISTEN/OWNER),
# and the "owning process" side of the check is a REAL short-lived helper
# process per host, so /proc/<pid>/cmdline content is genuinely read, not
# mocked away.
#
# Proves the exact bug class from the incident report:
#   - two different hosts get two different local ports (no collision)
#   - a second host never reuses the first host's tunnel
#   - the SAME host correctly reuses its own recorded tunnel
#   - a foreign/stale listener on the recorded port is rejected, not adopted
#   - state file entries for different hosts never collide/clobber

set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=rfb_view_portlib.sh
. "$here/rfb_view_portlib.sh"

declare -A LISTEN   # port -> 1 if something is "listening"
declare -A OWNER    # port -> pid whose real /proc/<pid>/cmdline "owns" it

# Overrides the real `ss` command for the whole test (this script sources
# rfb_view_portlib.sh into ITS OWN shell, so a function defined here takes
# priority over any $PATH ss for every call the sourced functions make).
ss() {
	case "$1" in
	-ltn)
		local p
		for p in "${!LISTEN[@]}"; do
			[ "${LISTEN[$p]}" = 1 ] && printf 'LISTEN 0 128 127.0.0.1:%s 0.0.0.0:*\n' "$p"
		done
		;;
	-ltnp)
		local p pid
		for p in "${!LISTEN[@]}"; do
			[ "${LISTEN[$p]}" = 1 ] || continue
			pid="${OWNER[$p]:-}"
			if [ -n "$pid" ]; then
				printf 'LISTEN 0 128 127.0.0.1:%s 0.0.0.0:* users:(("ssh",pid=%s,fd=6))\n' "$p" "$pid"
			fi
		done
		;;
	esac
}

# Spawns a real, short-lived background process whose argv contains
# "-L <port>:127.0.0.1:<remote_port> <host>" (the same shape a real ssh
# tunnel argv would have), so _rfb_view_tunnel_matches's real
# /proc/<pid>/cmdline read has real content to check, and prints its pid.
spawn_owner() { # local_port remote_port host
	# A `while` loop (not a single trailing simple command) so the shell
	# does not tail-call-optimize this into just "sleep N", which would
	# throw away the -N -L ... host tokens that make its /proc/<pid>/cmdline
	# stand in for a real ssh tunnel's argv.
	bash -c 'while :; do sleep 1; done' -N -L "$1:127.0.0.1:$2" "$3" </dev/null >/dev/null 2>&1 &
	disown
	echo $!
}

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done; }
trap cleanup EXIT

pass=0
fail=0
check() { # name got want
	if [ "$2" = "$3" ]; then
		pass=$((pass + 1))
	else
		fail=$((fail + 1))
		printf 'FAIL: %s: got [%s] want [%s]\n' "$1" "$2" "$3"
	fi
}

state="$(mktemp -d)/rfb_view-ports.state"
touch "$state"

# --- 1: two different hosts, both remote port 5901, must get distinct
#        local ports; neither may adopt the other's tunnel. -----------------
out_a="$(rfb_view_resolve_local_port water-banana 5901 "$state" 15901)"
port_a="${out_a% *}"; reuse_a="${out_a#* }"
pid_a="$(spawn_owner "$port_a" 5901 water-banana)"; pids+=("$pid_a")
LISTEN[$port_a]=1; OWNER[$port_a]=$pid_a

out_b="$(rfb_view_resolve_local_port water-coffee 5901 "$state" 15901)"
port_b="${out_b% *}"; reuse_b="${out_b#* }"
pid_b="$(spawn_owner "$port_b" 5901 water-coffee)"; pids+=("$pid_b")
LISTEN[$port_b]=1; OWNER[$port_b]=$pid_b

check "banana fresh alloc, no reuse" "$reuse_a" "0"
check "coffee fresh alloc, no reuse" "$reuse_b" "0"
if [ "$port_a" = "$port_b" ]; then
	fail=$((fail + 1))
	echo "FAIL: distinct hosts got the SAME local port ($port_a) - the exact bug"
else
	pass=$((pass + 1))
fi

# --- 2: same host again must REUSE its own real, still-listening tunnel. --
out_a2="$(rfb_view_resolve_local_port water-banana 5901 "$state" 15901)"
port_a2="${out_a2% *}"; reuse_a2="${out_a2#* }"
check "banana second call: same port" "$port_a2" "$port_a"
check "banana second call: reused=1" "$reuse_a2" "1"

# --- 3: coffee must still never be attributed banana's tunnel. -----------
out_b2="$(rfb_view_resolve_local_port water-coffee 5901 "$state" 15901)"
port_b2="${out_b2% *}"
check "coffee still not banana's port" "$([ "$port_b2" = "$port_a" ] && echo bad || echo ok)" "ok"

# --- 4: a stale/foreign owner on the recorded port must be rejected, ------
#        not silently adopted (the tunnel_matches host/port check).
kill "$pid_a" 2>/dev/null; wait "$pid_a" 2>/dev/null
foreign_pid="$(spawn_owner "$port_a" 9999 some-other-host)"; pids+=("$foreign_pid")
OWNER[$port_a]=$foreign_pid # LISTEN[$port_a] still 1: port still "listening"
out_a3="$(rfb_view_resolve_local_port water-banana 5901 "$state" 15901)"
port_a3="${out_a3% *}"; reuse_a3="${out_a3#* }"
check "foreign owner on old port: not reused" "$reuse_a3" "0"
check "foreign owner on old port: got a new port" "$([ "$port_a3" != "$port_a" ] && echo ok || echo bad)" "ok"
kill "$foreign_pid" 2>/dev/null

# --- 5: state file must hold exactly one, correct line per host. ---------
banana_line="$(awk '$1=="water-banana"{print}' "$state")"
coffee_line="$(awk '$1=="water-coffee"{print}' "$state")"
check "exactly one banana line" "$(awk '$1=="water-banana"' "$state" | wc -l)" "1"
check "exactly one coffee line" "$(awk '$1=="water-coffee"' "$state" | wc -l)" "1"
check "banana line matches latest port" "$banana_line" "water-banana $port_a3"
check "coffee line matches latest port" "$coffee_line" "water-coffee $port_b"

echo "----"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
