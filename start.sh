#!/bin/bash

# Navigate to the server directory
cd /home/test/Documents/server || exit

# 1. Forcefully kill ONLY the processes holding our specific ports (completely safe for VS Code)
fuser -k 5050/tcp 2>/dev/null
fuser -k 5055/tcp 2>/dev/null
fuser -k 3478/tcp 2>/dev/null
fuser -k 3478/udp 2>/dev/null

# Clean up any leftover background GUI jobs by matching the exact file name
pkill -f control_server.py 2>/dev/null

# Give the Linux kernel 1.5 seconds to fully release and free up the network ports
sleep 1.5

# 2. Automatically detect the active Wi-Fi IP address (ignoring proxy/VPN 198.18.x.x and localhost)
IP=$(ip -4 addr show | grep -v '198.18.' | grep -v '127.0.0.1' | sed -n 's/.*inet \([0-9.]*\)\/.*/\1/p' | head -n 1)
if [ -z "$IP" ]; then
    IP="127.0.0.1"
fi

echo "----------------------------------------"
echo "Detected Local Wi-Fi IP: $IP"

# 3. Update the config file with the current IP
if [ -f "screego.config" ]; then
    # Remove existing IP lines to prevent duplicates
    sed -i '/^SCREEGO_EXTERNAL_IP=/d' screego.config
else
    cp screego.config.example screego.config
fi
echo "SCREEGO_EXTERNAL_IP=$IP" >> screego.config

# 4. Define the room name
ROOM_NAME="a"

echo "Room to create: $ROOM_NAME"
echo "Students can join at: http://$IP:5050"
echo "----------------------------------------"

# 5. Start the python background control server (using your pyenv "python" binary)
python control_server.py &
PYTHON_PID=$!

# Ensure python helper closes if shell is closed
trap "kill $PYTHON_PID 2>/dev/null" EXIT

# 6. Wait 2 seconds for the Go server to boot, then auto-create the room in browser
(sleep 2 && xdg-open "http://localhost:5050/?room=$ROOM_NAME&create=true") &

# 7. Start the server (blocking command)
go run main.go serve