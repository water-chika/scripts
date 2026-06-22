#!/bin/sh

function get_focused_output_make()
{
	swaymsg -t get_outputs | jq -r '.. | select(.focused?) | .make'
}

function alacritty_get_focused_output_name()
{
	swaymsg -t get_outputs | jq -r '.. | select(.focused?) | .make + " " + .model'
}

export output_name=$(alacritty_get_focused_output_name)
export output_make=$(get_focused_output_make)

if test "$output_name" == 'DSC Paperlike H D'; then
	export TERM_THEME='gray'
elif test "$output_name" == 'Invalid Vendor Codename - RTK DS-DP'; then
	export TERM_THEME='eink'
elif test "$output_make" == 'Samsung Electric Company'; then
	export TERM_THEME='oled'
elif test "$output_make" == 'BOE'; then
	export TERM_THEME='oled'
else
	export TERM_THEME='default'
fi

case "$TERM_THEME" in
	"gray")
		alacritty -o 'colors.primary.foreground="#000000"' -o 'colors.primary.background="#ffffff"'
		;;
	"eink")
		alacritty -o 'colors.primary.foreground="#000000"' -o 'colors.primary.background="#ffffff"'
		;;
	"oled")
		alacritty -o 'colors.primary.foreground="#a0a0a0"' -o 'colors.primary.background="#000000"'
		;;
	*)
		alacritty -o 'colors.primary.foreground="#a0a0a0"' -o 'colors.primary.background="#000000"'
		;;
esac
