#!/bin/sh

xrandr --output DP-0 --primary --mode 1920x1200 --pos 0x307 --rotate normal --output DP-1 --off --output HDMI-0 --off --output DP-2 --off --output DP-3 --off --output DP-4 --mode 1920x1200 --pos 1920x0 --rotate left --output DP-5 --off
cp ~/bin/display/desk-cinnamon-monitors.xml ~/.config/cinnamon-monitors.xml

~/bin/display/move-sinks.sh "alsa_output.usb-Focusrite_Scarlett_2i2_USB-00.analog-stereo"
