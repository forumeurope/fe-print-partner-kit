#!/bin/bash
# Start the stand-in hub (development only). Optional argument: port.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found."
    echo "Install it from https://www.python.org/downloads/ or run: brew install python"
    exit 1
fi

port="${1:-8631}"
echo "Starting the stand-in hub on port $port. Press Ctrl-C to stop."
exec python3 fake-partner-hub.py --port "$port"
