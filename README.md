# HeadTracker

Head tracking software for racing and flight simulators. Uses a regular USB webcam to track your head movement and sends it to games via FreeTrack 2.0 or UDP protocol.

## Features

- **6DOF head tracking** — Yaw, Pitch, Roll, X, Y, Z
- **Webcam + IP + WebSocket cameras** — USB webcams, RTSP/HTTP IP streams, and phone WebSocket (MJPEG over ws) streams
- **Camera orientation** — Rotation (0°/90°/180°/270°) and mirror for sideways-mounted cameras
- **FreeTrack 2.0 output** — Windows shared memory (Assetto Corsa, BeamNG, ETS2, DCS, 800+ games)
- **UDP output** — Cross-platform network output (Linux, SteamOS, macOS)
- **Mouse output** — Mouse-look or cursor control from head pose (velocity/absolute modes)
- **Live overlay** — Face mesh, landmarks, and pose axes on camera preview
- **Per-axis settings** — Sensitivity, deadzone, inversion for each axis
- **Game presets** — Pre-configured profiles for popular simulators
- **Profile system** — Create, delete profiles; profiles apply instantly on selection
- **Stream stats** — FPS, frame time, bandwidth, resolution, dropped frames for IP cameras
- **Error handling** — Graceful recovery with user-facing error dialogs
- **Occlusion handling** — Smooth pose blending when face is partially covered
- **Low light enhancement** — CLAHE adaptive histogram equalization
- **High DPI support** — Proper scaling on 4K, 2K, and fractional DPI monitors (125%, 150%, 200%)
- **Threaded inference** — MediaPipe runs in background thread, UI stays responsive
- **Button debounce** — Protection against rapid double-clicks on all buttons
- **Localization** — English, Russian, Ukrainian, German (language selector in About tab)
- **Multi-platform** — Windows, Linux, macOS, SteamOS
- **System tray** — Minimize to tray, start/stop tracking and exit from the tray menu

## Quick Start

### Requirements

- Windows 10/11, Linux, macOS, or SteamOS
- Python 3.9+ (3.11+ recommended)
- USB webcam, IP camera, or a phone with a WebSocket stream app (e.g. DroidCam/IP Webcam)

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

**Windows (no terminal):**

```bash
HeadTracker.pyw          # Double-click — no console window
HeadTracker.bat          # Alternative launcher
```

**Windows (with terminal):**

```bash
start.bat              # Normal mode (no file logging)
start.bat -debug       # Debug mode (file + console logging)
start_debug.bat        # Shortcut for debug mode
```

**Linux / SteamOS (no terminal):**

```bash
chmod +x HeadTracker.sh
./HeadTracker.sh       # Runs in background, no terminal needed
```

**macOS (no terminal):**

```bash
chmod +x HeadTracker.command
./HeadTracker.command  # Double-click in Finder — launches without console
```

**Any platform (direct):**

```bash
python main.py              # Normal mode
python main.py -debug       # Debug mode (file + console logging)
python main.py -logging     # Same as -debug
```

## Usage

1. **Select camera** — Camera tab, pick a webcam, enter an IP/WebSocket URL
2. **Press Start** — Button turns yellow (⏳) then red (Stop), tracking begins
3. **Select profile** — Axes tab, pick a game preset from the dropdown
4. **Launch your game** — FreeTrack/UDP data is sent automatically
5. **Press Stop** — Button turns green (Start), tracking stops, all values reset to zero

> **Tip:** the game must be (re)started **after** tracking is running, with the same
> user privileges as the tracker — FreeTrack games read the shared memory at startup.

### UI Layout

```
┌──────────────────────────┬──────────────────────────┐
│  Camera Preview          │  Tabs                    │
│                          │  ┌────────────────────┐  │
│  [Start] [Stop]          │  │ Camera / Axes /    │  │
│                          │  │ Output / Log /     │  │
│  ┌───────┬─────────┐     │  │ About              │  │
│  │ Pose  │  Info   │     │  └────────────────────┘  │
│  │ Y/P/R │ Conf    │     │                          │
│  │ X/Y/Z │ FPS     │     │                          │
│  └───────┴─────────┘     │                          │
└──────────────────────────┴──────────────────────────┘
```

### Axes Tab

The Axes tab contains:
- **Profile selector** at the top — pick a profile or create a new one
- **Per-axis settings** — Enabled, Sensitivity, Deadzone, Inverted for each of 6 axes (Yaw, Pitch, Roll, X, Y, Z)

### Buttons

| Button | State | Action |
|--------|-------|--------|
| Start | 🟢 Green | Begin tracking → turns yellow (⏳) → red (Stop) |
| Stop | 🔴 Red | End tracking → turns green (Start) |
| New | — | Create a new profile by duplicating the current one |
| Delete | — | Delete the selected profile (Default cannot be deleted) |

All buttons have 800ms debounce protection against rapid clicks.

### IP Camera & WebSocket

For RTSP/HTTP cameras:

1. Camera tab → Source: `IP Camera (RTSP/HTTP)`
2. Enter URL: `rtsp://192.168.1.100:554/stream`
3. Press Start
4. Stream Stats panel shows FPS, frame time, bandwidth, resolution, dropped frames

For a phone used as a camera (e.g. IP Webcam, DroidCam, or a custom WebSocket stream):

1. Camera tab → Source: `WebSocket`
2. Enter URL: `ws://192.168.1.100:8080` (raw MJPEG frames or JSON with a base64 image field)
3. Press Start — frames are received over WebSocket and tracked as usual

### Camera Orientation

If the camera is mounted sideways or upside down:

1. Camera tab → **Rotation:** pick 90°/180°/270° until your face is upright in the preview
2. **Mirror** flips the image horizontally (selfie-style preview)

Both options are applied to the image, preview, and tracking consistently. After changing
them, keep your head straight for a second: Yaw/Pitch/Roll should read ≈ 0.

### Low Light

For dim environments, enable CLAHE image enhancement:

1. Camera tab → check `Enhance low light (CLAHE)`
2. Adaptive histogram equalization improves face detection in poor lighting

### Smoothing

Status tab → **Smoothing** slider (0–100%) applies exponential smoothing to the
whole head pose (yaw/pitch/roll and position) before it is sent to any protocol.
Higher values feel smoother but add lag; start around 50%. It is reset when the
face is lost and re-acquired.

### Output Protocols

| Protocol | Platform | Use case |
|----------|----------|----------|
| FreeTrack | Windows | 800+ sim racing/flight games via shared memory |
| UDP | All | Cross-platform network output, games that support UDP trackers |
| Mouse | All | Moves the system mouse from head pose — mouse-look in games without tracker support |

The Output tab shows a **protocol log** (updates every ~60 frames) with the raw
pose and `conf` — useful to verify tracking before launching the game.

### Crash dumps

If the app crashes (unhandled exception, fatal error in the tracking thread, or a
native fault in MediaPipe/OpenCV), a dump is written to the `logs/` folder with a
filename starting with `crash`:

- `crash_YYYY-MM-DD_HH-MM-SS.log` — traceback of an unhandled Python exception
  (main thread, worker thread, or output error), with Python version, platform and CWD;
- `crash_native_*.log` — faulthandler dump for native faults (segfault/abort).
  Empty files are removed automatically on a clean exit.

Attach these files when reporting a crash.

### Mouse

Useful for games that have no FreeTrack/UDP support but accept mouse input:

1. Output tab → Protocol: `Mouse`
2. **Mode: Velocity (mouse-look)** — while your head is turned, the view pans;
   returning to center stops it. Good for racing/flight/FPS games with mouse-look.
   **Mode: Absolute (cursor)** — the cursor is positioned on the screen
   proportionally to yaw/pitch, useful for desktop navigation.
3. **Mouse speed** — velocity: pixels per second per degree; absolute: pixels per degree.
   Direction inversion and deadzone are taken from the profile axes (Yaw/Pitch).
4. **Stop method** — the mouse moves only while you **hold** the hotkey
   (default `F8`, release to stop), or **toggles** with each press.
   Use it to pause the view without returning your head to center.

Pose is smoothed (EMA) and a small minimum deadzone is applied so small head
jitter (especially the pitch drift while turning your head sideways) does not
move the cursor unexpectedly.

> **Note:** some games read the mouse via Raw Input and ignore programmatically
> injected movement (SendInput/pynput). Such games will not respond to Mouse output;
> FreeTrack or UDP remain the reliable options there.

### Exit Confirmation

When tracking is active, closing the window shows a warning dialog: "Отслеживание активно. Вы уверены, что хотите выйти?" — prevents accidental exit.

### Localization

Language selector in the About tab. Changes apply instantly without restart:
- English, Русский, Українська, Deutsch

### Linux / macOS / SteamOS Notes

- FreeTrack shared memory is Windows-only — use **UDP output** on Linux/macOS
- Camera uses V4L2 backend (Linux) or AVFoundation (macOS)
- Face detection model downloaded by `setup.sh`
- SteamOS: run in desktop mode for camera access

### Troubleshooting

| Symptom | Check |
|---------|-------|
| Game does not react at all | Start tracking, **then** restart the game; run both with the same privileges (both normal or both admin); make sure the game has FreeTrack/TrackIR enabled and the Output tab shows the right protocol |
| View is upside down or jerky | Head straight → pose numbers should read ≈ 0 (not ±180°). If Roll flips between ±180°, camera rotation/mirror are misconfigured — fix in Camera tab |
| Tracking works but values are noisy | Lower per-axis sensitivity in the Axes tab; check the Confidence field stays above 0.3 |
| Game turns the wrong way | Toggle **Inverted** for the affected axis in the profile |
| FreeTrack status shows an error | Run `start_debug.bat` and check `logs/` — the log shows whether shared memory and registry keys were created |

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

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Main Thread (Qt GUI)                               │
│                                                     │
│  Camera preview ←── frame_ready signal              │
│  Pose labels    ←── pose_ready signal               │
│  Status bar     ←── confidence_ready signal         │
│  Profile/settings UI (user interaction)             │
│                                                     │
│  overlay drawing (cv2) on frame from worker         │
└──────────────────────┬──────────────────────────────┘
                       │ signals
┌──────────────────────┴──────────────────────────────┐
│  Worker Thread (QThread)                            │
│                                                     │
│  Camera.get_frame()        ← blocking read          │
│  HeadTracker.process_frame() ← ML inference (10-50ms)│
│  axis mapping (sensitivity, deadzone, inversion)     │
│  output.send_pose() (FreeTrack / UDP)               │
│                                                     │
│  Runs at ~60fps with time.sleep() pacing            │
└─────────────────────────────────────────────────────┘
```

MediaPipe inference (the most expensive operation) runs in a background thread, keeping the UI responsive during tracking. The main thread only handles UI updates and overlay drawing.

## Project Structure

```
HeadTracker/
├── main.py                # Entry point, logging, splash screen
├── HeadTracker.pyw        # Windows: no-console launcher
├── HeadTracker.bat        # Windows: no-console launcher (alt)
├── HeadTracker.sh         # Linux/macOS: no-terminal launcher
├── HeadTracker.command    # macOS: native double-click launcher
├── setup.bat / setup.sh   # First-run setup (Python check, deps, model)
├── start.bat / start.sh   # Launch scripts (with terminal)
├── i18n.py                # Localization (en, ru, uk, de)
├── camera.py              # Webcam + IP camera capture, frame stats
├── tracker.py             # MediaPipe FaceLandmarker + PnP head pose
├── filter.py              # One Euro Filter, Exponential, Passthrough
├── worker.py              # Background tracking thread (QThread)
├── freetrack.py           # FreeTrack 2.0 shared memory (Windows-only)
├── udp_output.py          # UDP output (cross-platform)
├── config.py              # Profile, AxisConfig, AppSettings, JSON I/O
├── ui/
│   └── main_window.py     # PySide6 GUI, overlay, profile management
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

## License

This project uses third-party libraries with permissive licenses. See `THIRD_PARTY_LICENSES` for details.
