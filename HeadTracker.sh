#!/bin/bash
cd "$(dirname "$0")"
nohup python3 main.py > /dev/null 2>&1 &
