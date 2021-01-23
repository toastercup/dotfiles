#!/bin/bash

if pgrep -x "foobar2000.exe" >/dev/null
then
    foobar2000 "-$1"
else
    if [ "$1" = "playpause" ]
    then
        dbus-send --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.PlayPause
    elif [ "$1" = "next" ]
    then
        dbus-send --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Next
    elif [ "$2" = "prev" ]
    then
        dbus-send --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Previous
    fi
fi

