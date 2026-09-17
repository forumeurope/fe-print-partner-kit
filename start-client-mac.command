#!/bin/bash
# Start the example print client. Optional arguments: hub address, hub port.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found."
    echo "Install it from https://www.python.org/downloads/ or run: brew install python"
    exit 1
fi

hub="${1:-}"
if [ -z "$hub" ]; then
    read -r -p "Hub address [127.0.0.1]: " hub
    hub="${hub:-127.0.0.1}"
fi
port="${2:-8631}"

echo "Collecting badges from $hub:$port into $(pwd)/badges. Press Ctrl-C to stop."
exec python3 print-partner-client.py --hub "$hub" --port "$port" --out badges
