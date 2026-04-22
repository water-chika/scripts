#!/bin/sh

function alacritty_switch_theme()
{
if test $1 == 'gray'; then
alacritty msg config 'colors.primary.foreground="#000000"'
alacritty msg config 'colors.primary.background="#ffffff"'
unset COLORTERM
export TERM=xtermm
unset LS_COLORS
unalias ls
elif test $1 == 'eink'; then
alacritty msg config 'colors.primary.foreground="#000000"'
alacritty msg config 'colors.primary.background="#ffffff"'
elif test $1 == 'oled'; then
alacritty msg config 'colors.primary.foreground="#a0a0a0"'
alacritty msg config 'colors.primary.background="#000000"'
fi
}

function get_focused_output_make()
{
	swaymsg -t get_outputs | jq -r '.. | select(.focused?) | .make'
}

function alacritty_get_focused_output_name()
{
	swaymsg -t get_outputs | jq -r '.. | select(.focused?) | .make + " " + .model'
}

if test $TERM == 'alacritty'; then
	export output_name=$(alacritty_get_focused_output_name)
	export output_make=$(get_focused_output_make)
	if test "$output_name" == 'DSC Paperlike H D'; then
		alacritty_switch_theme gray
	elif test "$output_name" == 'Invalid Vendor Codename - RTK DS-DP'; then
		alacritty_switch_theme eink
	elif test "$output_make" == 'Samsung Electric Company'; then
		alacritty_switch_theme oled
	elif test "$output_make" == 'BOE'; then
		alacritty_switch_theme oled
	else
		alacritty_switch_theme eink
	fi
fi
