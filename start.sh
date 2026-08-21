#!/bin/bash

# Navigate to the server directory
cd /var/mnt/shared-drive/2027/ComputerScripts/server || exit

# Ensure Go and Host Python Venv are in PATH
export PATH="$HOME/.local/go/bin:$HOME/go/bin:$PATH"
PYTHON_BIN="$HOME/.local/server-venv/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

BUILD_UI="${BUILD_UI:-false}"

for arg in "$@"; do
    case $arg in
        --build|-b|build)
            BUILD_UI=true
            ;;
        --no-build|-nb|nobuild)
            BUILD_UI=false
            ;;
    esac
done

if [ "$BUILD_UI" = "true" ]; then
    echo "----------------------------------------"
    echo "Rebuilding React Frontend with Deno..."
    echo "----------------------------------------"
    cd ui || exit
    deno install
    deno task build
    cd ..
else
    echo "----------------------------------------"
    echo "Skipping React Frontend build (BUILD_UI=false)"
    echo "----------------------------------------"
fi

# 1. Kill processes holding specific ports
fuser -k 5050/tcp 2>/dev/null
fuser -k 5055/tcp 2>/dev/null
fuser -k 3478/tcp 2>/dev/null
fuser -k 3478/udp 2>/dev/null
pkill -f control_server.py 2>/dev/null

sleep 1.5

# 2. Automatically detect Wi-Fi IP
IP=$(ip -4 addr show | grep -v '198.18.' | grep -v '127.0.0.1' | sed -n 's/.*inet \([0-9.]*\)\/.*/\1/p' | head -n 1)
if [ -z "$IP" ]; then
    IP="127.0.0.1"
fi

echo "----------------------------------------"
echo "Detected Local Wi-Fi IP: $IP"

# 3. Update screego config
if [ -f "screego.config" ]; then
    sed -i '/^SCREEGO_EXTERNAL_IP=/d' screego.config
else
    cp screego.config.example screego.config
fi
echo "SCREEGO_EXTERNAL_IP=$IP" >> screego.config

# 4. Create and set PipeWire VirtualMic directly on Host
DEFAULT_SINK=$(pactl get-default-sink 2>/dev/null)
if [ -n "$DEFAULT_SINK" ]; then
    pactl unload-module module-remap-source 2>/dev/null
    echo "Routing Computer Audio Output (No Mic) -> VirtualMic"
    pactl load-module module-remap-source source_name=VirtualMic master="${DEFAULT_SINK}.monitor" source_properties=device.description=VirtualMic 2>/dev/null
    pactl set-default-source VirtualMic 2>/dev/null
    pactl set-source-mute VirtualMic 0 2>/dev/null
    pactl set-source-volume VirtualMic 100% 2>/dev/null
fi

ROOM_NAME="a"
echo "Room to create: $ROOM_NAME"
echo "Students can join at: http://$IP:5050"
echo "----------------------------------------"

ROOM_URL="http://127.0.0.1:5050/?room=$ROOM_NAME&create=true"

# Launch host python GUI
(sleep 2 && $PYTHON_BIN control_server.py "$ROOM_URL") &
SUBSHELL_PID=$!

trap "kill $SUBSHELL_PID 2>/dev/null; pkill -f control_server.py 2>/dev/null" EXIT

# Start Go Server natively on host
go run . serve