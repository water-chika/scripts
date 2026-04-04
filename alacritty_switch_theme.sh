#!/bin/sh

function alacritty_switch_theme()
{
if test $1 == 'gray'; then
alacritty msg config 'colors.primary.foreground="#000000"'
alacritty msg config 'colors.primary.background="#ffffff"'
unset COLORTERM
export TERM=xtermm
unset LS_COLORS
elif test $1 == 'eink'; then
alacritty msg config 'colors.primary.foreground="#000000"'
alacritty msg config 'colors.primary.background="#ffffff"'
elif test $1 == 'oled'; then
alacritty msg config 'colors.primary.foreground="#a0a0a0"'
alacritty msg config 'colors.primary.background="#000000"'
fi
}

function alacritty_get_focused_output_name()
{
	swaymsg -t get_outputs | jq -r '.. | select(.focused?) | .make + " " + .model'
}

if test $TERM == 'alacritty'; then
	export output_name=$(alacritty_get_focused_output_name)
	if test "$output_name" == 'DSC Paperlike H D'; then
		alacritty_switch_theme gray
	elif test "$output_name" == 'Invalid Vendor Codename - RTK DS-DP'; then
		alacritty_switch_theme eink
	elif test "$output_name" == 'Samsung Electric Company Odyssey G81SF'; then
		alacritty_switch_theme oled
	fi
fi
