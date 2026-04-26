#!/usr/bin/bash

name=$(swaymsg -t get_outputs | jq -r '.[] | select(.name=="HEADLESS-1") | .name')

if test $name != "HEADLESS-1"; then
	swaymsg create_output
	swaymsg output HEADLESS-1 mode 2480x1860 allow_tearing yes scale 2
fi

wayvnc --output=HEADLESS-1 --disable-input --render-cursor 127.0.0.1 &
ssh tablet.water.n2n -R 127.0.0.1:5900:127.0.0.1:5900 -N
