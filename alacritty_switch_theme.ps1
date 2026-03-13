param(
    $Theme
)
if ($Theme -eq 'gray') {
    alacritty msg config 'colors.primary.foreground="#000000"'
    alacritty msg config 'colors.primary.background="#ffffff"'
}
elseif ($Theme -eq 'eink') {
    alacritty msg config 'colors.primary.foreground="#000000"'
    alacritty msg config 'colors.primary.background="#ffffff"'
}
elseif ($Theme -eq 'oled') {
    alacritty msg config 'colors.primary.foreground="#a0a0a0"'
    alacritty msg config 'colors.primary.background="#000000"'
}
