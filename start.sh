#!/bin/bash
cd "$(dirname "$0")"
echo "Starting HeadTracker..."
python3 main.py "$@"
