#!/bin/bash
cd "$(dirname "$0")"
open -a Python main.py 2>/dev/null || python3 main.py &
