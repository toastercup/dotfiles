#!/bin/sh

xrandr --output DP-0 --off --output DP-1 --off --output HDMI-0 --primary --mode 1920x1080 --pos 0x0 --rotate normal --scale 0.8x0.8 --output DP-2 --off --output DP-3 --off --output DP-4 --off --output DP-5 --off
cp ~/bin/display/tv-cinnamon-monitors.xml ~/.config/cinnamon-monitors.xml

~/bin/display/move-sinks.sh "alsa_output.pci-0000_01_00.1.hdmi-stereo-extra1"
