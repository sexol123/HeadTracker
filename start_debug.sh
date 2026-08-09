#!/bin/bash
cd "$(dirname "$0")"
echo "Starting HeadTracker in debug mode..."
python3 main.py -debug -logging "$@"
