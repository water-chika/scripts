#!/bin/sh
# Start sway.
#
# From a TTY -- no Wayland/X session in the environment -- this starts the real
# desktop session, exactly as it always has.
#
# Run from INSIDE an existing session (an agent or a script calling it from a
# terminal on the desktop), wlroots would otherwise auto-select the wayland
# backend and open a nested "wlroots - WL-1" window on the live desktop, which
# is never what the caller meant. So in that case this script sanitises its own
# environment and runs headless: it renders to memory and cannot steal focus.
# Doing it here rather than in the caller means a tool invoked from anywhere
# does the right thing by default.
#
# A visible nested window is available, but only on purpose:
#   sway_start.sh --nested
#   SWAY_START_NESTED=1 sway_start.sh
set -eu

export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx

nested="${SWAY_START_NESTED:-0}"
if [ "${1:-}" = "--nested" ]; then
	nested=1
	shift
fi

if [ "$nested" != 1 ] && {
	[ -n "${WAYLAND_DISPLAY:-}" ] ||
		[ -n "${SWAYSOCK:-}" ] ||
		[ -n "${DISPLAY:-}" ]
}; then
	# Inherited someone else's session: do not draw into it.
	unset WAYLAND_DISPLAY SWAYSOCK DISPLAY
	WLR_BACKENDS=headless
	WLR_LIBINPUT_NO_DEVICES=1
	export WLR_BACKENDS WLR_LIBINPUT_NO_DEVICES
fi

exec sway "$@"
