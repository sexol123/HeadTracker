#!/bin/bash
cd "$(dirname "$0")"
echo "=== HeadTracker Setup ==="
echo ""

# Check Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[ERROR] Python 3.11+ not found. Please install Python 3.11 or newer."
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  Fedora: sudo dnf install python3 python3-pip"
    echo "  Arch: sudo pacman -S python python-pip"
    echo "  SteamOS: sudo pacman -S python python-pip"
    exit 1
fi

PY_VER=$($PYTHON --version 2>&1)
echo "[OK] $PY_VER"

# Install dependencies
echo "Installing dependencies..."
$PYTHON -m pip install --user -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install dependencies"
    exit 1
fi
echo "[OK] Dependencies installed"

# Download model
mkdir -p models
MODEL="models/face_landmarker.task"
if [ -f "$MODEL" ]; then
    echo "[OK] Model already exists"
else
    echo "Downloading face landmark model..."
    curl -L -o "$MODEL" "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
    if [ $? -ne 0 ] || [ ! -s "$MODEL" ]; then
        echo "[ERROR] Failed to download model"
        rm -f "$MODEL"
        exit 1
    fi
    echo "[OK] Model downloaded"
fi

POSE_MODEL="models/pose_landmarker_full.task"
if [ -f "$POSE_MODEL" ]; then
    echo "[OK] Pose model already exists"
else
    echo "Downloading pose landmark model (side-view fallback)..."
    curl -L -o "$POSE_MODEL" "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task"
    if [ $? -ne 0 ] || [ ! -s "$POSE_MODEL" ]; then
        echo "[WARNING] Failed to download pose model (optional)."
        echo "  Place it manually in: models/pose_landmarker_full.task"
        rm -f "$POSE_MODEL"
    else
        echo "[OK] Pose model downloaded"
    fi
fi

echo ""
echo "=== Setup complete! ==="
echo "Run: ./start.sh"
