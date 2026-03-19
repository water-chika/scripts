#!/bin/sh

function alacritty_switch_theme()
{
if test $1 == 'gray'; then
alacritty msg config 'colors.primary.foreground="#000000"'
alacritty msg config 'colors.primary.background="#ffffff"'
unset COLORTERM
export TERM=xtermm
elif test $1 == 'eink'; then
alacritty msg config 'colors.primary.foreground="#000000"'
alacritty msg config 'colors.primary.background="#ffffff"'
elif test $1 == 'oled'; then
alacritty msg config 'colors.primary.foreground="#a0a0a0"'
alacritty msg config 'colors.primary.background="#000000"'
fi
}
