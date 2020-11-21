#!/bin/sh

if [ -n "$( xrandr -q | grep 'DP-0 connected primary' )" ]
then
    ~/bin/tv.sh
    echo "Switched to TV…"
else
    ~/bin/desk.sh
    echo "Switched to desk displays…"
fi
