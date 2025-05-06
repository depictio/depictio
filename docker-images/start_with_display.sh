#!/bin/bash
# Start Xvfb
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Start a window manager
fluxbox &

# Start VNC server
x11vnc -display :99 -nopw -forever -shared &

# Start your application
python depictio/api/run.py
