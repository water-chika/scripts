#!/usr/bin/bash

swaymsg create-output
swaymsg output HEADLESS-1 mode 2480x1860 allow_tearing yes

swayvnc --output=HEADLESS-1 --disable-input --render-cursor 127.0.0.1 &
ssh tablet.water.n2n -R 127.0.0.1:5900:127.0.0.1:5900 -N
