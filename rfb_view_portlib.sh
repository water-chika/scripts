#!/usr/bin/env bash
# rfb_view_portlib.sh - the per-host local-tunnel-port bookkeeping used by
# rfb_view.sh, split into its own file so it can be sourced and unit tested
# directly (test_rfb_view_portlib.sh) without spawning a real ssh tunnel or
# viewer.
#
# The bug this exists to fix: the local forward port used to be derived
# from the REMOTE port only ($PORT + 10000), so two different hosts whose
# rfb_server both happen to listen on the same remote port (5901 is the
# common default) collapsed onto the SAME local tunnel - the second host's
# viewer silently showed the FIRST host's desktop. Now the local port is
# recorded per host in a state file, and "is a tunnel already there"
# is answered by checking who is ACTUALLY listening (their real ssh argv),
# never assumed from the port number alone.

_rfb_view_recorded_port() {  # host state_file
	awk -v h="$1" '$1==h{print $2; exit}' "$2" 2>/dev/null
}

_rfb_view_tunnel_matches() {  # local_port host remote_port
	local port="$1" host="$2" remote="$3" owner_pid owner_cmd
	ss -ltn 2>/dev/null | grep -q "127.0.0.1:$port " || return 1
	owner_pid="$(ss -ltnp 2>/dev/null | awk -v p=":$port\$" '$4 ~ p {
		match($0, /pid=([0-9]+)/, m); print m[1]; exit}' 2>/dev/null)"
	[ -n "$owner_pid" ] && [ -r "/proc/$owner_pid/cmdline" ] || return 1
	owner_cmd=" $(tr '\0' ' ' < "/proc/$owner_pid/cmdline" 2>/dev/null) "
	# host and remote-port must both appear as whole tokens, but NOT
	# necessarily with a gap between them - e.g. ssh's own argv often has
	# them adjacent ("...:5901 water-banana", a single shared space), so
	# they are checked independently rather than as one glob requiring two
	# separate spaces between adjacent tokens (that requirement silently
	# never matched real ssh argv and made "reuse" never fire).
	case "$owner_cmd" in *" $host "*) : ;; *) return 1 ;; esac
	case "$owner_cmd" in *":$remote "*) : ;; *) return 1 ;; esac
	return 0
}

# Prints "<local_port> <0|1>" (1 = an existing tunnel can be reused) and
# updates state_file in place - never leaving a duplicate/stale line for
# this host, and never touching another host's line.
#
# forced_port (5th arg, e.g. $RFB_VIEW_LOCAL_PORT) pins the port instead of
# using/allocating the recorded one, but still goes through the same
# verified-reuse check and the same state bookkeeping.
rfb_view_resolve_local_port() {  # host remote_port state_file [start_port] [forced_port]
	local host="$1" remote="$2" state="$3" start="${4:-15901}" forced="${5:-}"
	local recorded used port
	if [ -n "$forced" ]; then
		if _rfb_view_tunnel_matches "$forced" "$host" "$remote"; then
			printf '%s 1\n' "$forced"
			return 0
		fi
		awk -v h="$host" '$1!=h' "$state" > "$state.tmp" 2>/dev/null
		printf '%s %s\n' "$host" "$forced" >> "$state.tmp"
		mv "$state.tmp" "$state"
		printf '%s 0\n' "$forced"
		return 0
	fi
	recorded="$(_rfb_view_recorded_port "$host" "$state")"
	if [ -n "$recorded" ] && _rfb_view_tunnel_matches "$recorded" "$host" "$remote"; then
		printf '%s 1\n' "$recorded"
		return 0
	fi
	used="$(awk -v h="$host" '$1!=h{print $2}' "$state" 2>/dev/null)"
	port="${recorded:-$start}"
	while :; do
		case " $used " in *" $port "*) port=$((port + 1)); continue ;; esac
		ss -ltn 2>/dev/null | grep -q "127.0.0.1:$port " || break
		port=$((port + 1))
	done
	awk -v h="$host" '$1!=h' "$state" > "$state.tmp" 2>/dev/null
	printf '%s %s\n' "$host" "$port" >> "$state.tmp"
	mv "$state.tmp" "$state"
	printf '%s 0\n' "$port"
}
