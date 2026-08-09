# HeadTracker

Head tracking software for racing and flight simulators. Uses a regular USB webcam to track your head movement and sends it to games via FreeTrack 2.0 protocol.

## Features

- **6DOF head tracking** — Yaw, Pitch, Roll, X, Y, Z
- **Webcam + IP camera** — USB webcams and RTSP/HTTP IP camera streams
- **FreeTrack 2.0 output** — Windows shared memory (Assetto Corsa, BeamNG, ETS2, DCS, 800+ games)
- **UDP output** — Cross-platform network output (Linux, SteamOS, macOS)
- **Live overlay** — See face mesh, landmarks, and pose axes on camera preview
- **Fullscreen centering** — Dedicated dialog with crosshair, face status, and one-click centering
- **Per-axis settings** — Sensitivity, deadzone, inversion for each axis
- **Game presets** — Pre-configured profiles for popular simulators
- **Profile system** — Create, save, duplicate, export/import profiles; Default profile is immutable
- **Stream stats** — FPS, frame time, bandwidth, resolution, dropped frames for IP cameras
- **Error handling** — Graceful recovery with user-facing error dialogs
- **Occlusion handling** — Smooth pose blending when face is partially covered, prevents in-game jitter
- **Low light enhancement** — CLAHE adaptive histogram equalization for better tracking in dim environments
- **High DPI support** — Proper scaling on 4K, 2K, and fractional DPI monitors (125%, 150%, 200%)
- **Multi-platform** — Windows, Linux, SteamOS

## Quick Start

### Requirements

- Windows 10/11, Linux, or SteamOS
- Python 3.9+ (3.11+ recommended)
- USB webcam or IP camera

### Windows

Run `setup.bat` — it checks Python, installs pip dependencies, and downloads the face model:

```bash
setup.bat
```

Or install manually:

```bash
python -m pip install mediapipe opencv-python PySide6 numpy pynput
```

### Linux / SteamOS

```bash
chmod +x setup.sh
./setup.sh
```

Or install manually:

```bash
python3 -m pip install mediapipe opencv-python PySide6 numpy pynput
```

### Run

**Windows:**

```bash
start.bat              # Normal mode (no file logging)
start.bat -debug       # Debug mode (file + console logging)
start_debug.bat        # Shortcut for debug mode
```

**Linux / SteamOS:**

```bash
./start.sh             # Normal mode
./start_debug.sh       # Debug mode
```

**Any platform (direct):**

```bash
python main.py              # Normal mode
python main.py -debug       # Debug mode (file + console logging)
python main.py -logging     # Same as -debug
```

## Usage

1. **Select camera** — Camera tab, pick your webcam or enter IP camera URL
2. **Press Start** — Tracking begins, you see face mesh overlay
3. **Press Center (F12)** — Opens fullscreen centering dialog
4. **Launch your game** — FreeTrack data is sent automatically
5. **Press Reset (F11)** — Returns virtual camera to center

### Centering Dialog

When you press Center (F12), a fullscreen dialog opens with:
- Live camera preview with crosshair
- Face detection status (green = OK, red = no face)
- Large CENTER button — press to set current pose as center
- ESC to cancel without changing center

### Hotkeys

| Key | Action |
|-----|--------|
| F12 | Center (open centering dialog) |
| F11 | Reset (return to center) |

### IP Camera

For RTSP cameras:

1. Camera tab → Source: `IP Camera (RTSP/HTTP)`
2. Enter URL: `rtsp://192.168.1.100:554/stream`
3. Press Start
4. Stream Stats panel shows FPS, frame time, bandwidth, resolution, dropped frames

### Low Light

For dim environments, enable CLAHE image enhancement:

1. Camera tab → check `Enhance low light (CLAHE)`
2. Adaptive histogram equalization improves face detection in poor lighting

### Output Protocols

| Protocol | Platform | Use case |
|----------|----------|----------|
| FreeTrack | Windows | 800+ sim racing/flight games via shared memory |
| UDP | All | Cross-platform network output, games that support UDP trackers |

### Linux / SteamOS Notes

- FreeTrack shared memory is Windows-only — use **UDP output** on Linux
- Camera uses V4L2 backend (default on Linux)
- Face detection model downloaded by `setup.sh`
- SteamOS: run in desktop mode for camera access

## Supported Games

### Windows (FreeTrack)

Any game that supports FreeTrack or TrackIR protocol:

| Game | Preset |
|------|--------|
| Assetto Corsa | `assetto_corsa.json` |
| Assetto Corsa Competizione | `assetto_corsa_competizione.json` |
| BeamNG.drive | `beamng.json` |
| Euro Truck Simulator 2 | `ets2.json` |
| American Truck Simulator | `ats.json` |
| DCS World | `dcs.json` |
| War Thunder | `war_thunder.json` |
| WRC | `wrc.json` |

### Linux / SteamOS (UDP)

Use UDP output in games that support UDP head tracking (e.g., through opentrack UDP receiver).

## Project Structure

```
HeadTracker/
├── main.py                # Entry point, logging setup
├── setup.bat              # Windows first-run setup
├── setup.sh               # Linux/SteamOS first-run setup
├── start.bat              # Windows launch script
├── start.sh               # Linux/SteamOS launch script
├── start_debug.bat        # Windows debug launch
├── start_debug.sh         # Linux/SteamOS debug launch
├── camera.py              # Webcam + IP camera capture, frame stats
├── tracker.py             # MediaPipe FaceLandmarker + PnP head pose
├── filter.py              # One Euro Filter, Exponential, Passthrough
├── freetrack.py           # FreeTrack 2.0 shared memory (Windows-only)
├── udp_output.py          # UDP output (cross-platform)
├── config.py              # Profile, AxisConfig, AppSettings, JSON I/O
├── ui/
│   ├── main_window.py     # PySide6 GUI, overlay, profile management
│   └── center_dialog.py   # Fullscreen centering dialog
├── models/                # MediaPipe face_landmarker.task
├── profiles/              # Game preset profiles (JSON)
├── settings.json          # App settings (auto-saved, gitignored)
├── logs/                  # Debug session logs (gitignored)
├── ROADMAP.md             # Development roadmap
├── THIRD_PARTY_LICENSES   # Dependency licenses
└── .gitignore
```

## Technology

| Component | Library | License |
|-----------|---------|---------|
| Face tracking | MediaPipe FaceLandmarker | Apache 2.0 |
| Head pose | OpenCV solvePnP | Apache 2.0 |
| GUI | PySide6 | LGPL v3 |
| Camera | OpenCV | Apache 2.0 |
| Hotkeys | pynput | LGPL v3 |

## License

This project uses third-party libraries with permissive licenses. See `THIRD_PARTY_LICENSES` for details.
