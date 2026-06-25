#!/bin/sh

exec filename=~/Pictures/screenshot_$(date +%Y_%m_%d_%H_%S_%N).png && slurp | grim -g - $filename && wl-copy < $filename

# current focused display full screen shot
#exec filename=~/Pictures/screenshot_$(date +%Y_%m_%d_%H_%S_%N).png && grim -o $(swaymsg -t get_outputs | jq -r '.. | select(.focused?) | .name') $filename
