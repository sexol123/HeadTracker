# HeadTracker

Head tracking software for racing and flight simulators. Uses a regular USB webcam to track your head movement and sends it to games via FreeTrack 2.0 or UDP protocol.

## Features

- **6DOF head tracking** — Yaw, Pitch, Roll, X, Y, Z
- **Webcam + IP + WebSocket cameras** — USB webcams, RTSP/HTTP IP streams, and phone WebSocket (MJPEG over ws) streams
- **Android companion app** — `HeadTrackerCam` turns any Android phone into a low-latency wireless (Wi-Fi) or wired (USB via `android_usb.bat`) camera, streaming raw MJPEG over WebSocket with no protocol changes on the desktop
- **Camera orientation** — Rotation (0°/90°/180°/270°) and mirror for sideways-mounted cameras
- **FreeTrack 2.0 output** — Windows shared memory (Assetto Corsa, BeamNG, ETS2, DCS, 800+ games)
- **UDP output** — Cross-platform network output (Linux, SteamOS, macOS)
- **Mouse output** — Mouse-look or cursor control from head pose (velocity/absolute modes)
- **Live overlay** — Face mesh with three detail levels (contours / medium / full, all drawn with thin 1 px lines), landmarks, and pose axes on camera preview
- **Dual preview** — Camera feed and the cockpit (in-game) view are always shown together, one above the other, so raw tracking and the exact view the game receives are compared live; cockpit yaw mirrors the in-game direction
- **Per-axis settings** — Sensitivity, deadzone, inversion for each axis
- **Nonlinear response curves** — second bend point per axis (like opentrack): boost small movements without hitting the ceiling on large ones
- **Multi-face selection** — when several people are in the frame, pick which face to track (stays locked to that person)
- **Full-circle head tracking** — when the face is not visible (profile views, turning around), a BlazePose fallback tracks the head via nose/eyes/ears, keeping yaw continuous up to ±175° and switching seamlessly back when the face reappears
- **Adaptive smoothing** — Accela-style pose filter: suppresses jitter and stays stable even when looking straight up, without slowing fast moves
- **Degenerate pose rejection** — single-frame PnP spikes (impossible angles, ~1.7 m jumps) are held as the last valid pose instead of jerking the game view; confidence fades out so nothing bad is sent
- **Calibration wizard** — guided setup: mark the camera position on the monitor, set center, record left/right/up/down head motions; measures direction, gain, jitter and lag per axis and proposes sensitivity/inversion/recenter changes
- **Tuning assistant** — records your real head movements while tracking and suggests exact per-axis changes (sensitivity, inversion, smoothing) applied with one click
- **Profile system** — Create, delete profiles; profiles apply instantly on selection; center pose and response curves are stored per profile
- **Live settings** — Profile, per-axis settings, smoothing, camera rotation/mirror/CLAHE, camera adaptation and mouse options change instantly while tracking runs
- **Auto-save** — Settings and profile edits are saved automatically (debounced), not only on exit
- **Camera stall recovery** — detects a dead camera stream (e.g. after sleep/hibernate) and reconnects automatically, with up to 5 retries
- **Stream stats** — FPS, frame time, bandwidth, resolution, dropped frames for IP cameras
- **Performance graph** — 10-second live graph of FPS/frame time/tracking latency with reconnect markers in the Log tab
- **Error handling** — Graceful recovery with user-facing error dialogs
- **Hotkey combos** — Mouse output hotkeys support modifiers (Ctrl/Alt/Ctrl+Shift), not just single keys
- **Occlusion handling** — Smooth pose blending when face is partially covered
- **Low light enhancement** — CLAHE adaptive histogram equalization
- **High DPI support** — Proper scaling on 4K, 2K, and fractional DPI monitors (125%, 150%, 200%)
- **Threaded inference** — MediaPipe runs in background thread, UI stays responsive
- **Button debounce** — Protection against rapid double-clicks on all buttons
- **Localization** — English, Russian, Ukrainian, German (language selector in About tab)
- **Multi-platform** — Windows, Linux, macOS, SteamOS
- **System tray** — Minimize to tray, start/stop tracking and exit from the tray menu
- **Minimize auto-pause** — Minimizing the window pauses tracking (camera + inference stop, saving CPU); restoring the window resumes it automatically

## Quick Start

### Requirements

- Windows 10/11, Linux, macOS, or SteamOS
- Python 3.11+
- USB webcam, IP camera, or a phone with the **HeadTrackerCam** app (or DroidCam/IP Webcam)

### Windows

Run `setup.bat` — it checks Python, installs pip dependencies, and downloads the face model and the optional pose model (side-view fallback):

```bash
setup.bat
```

Or install manually:

```bash
python -m pip install mediapipe opencv-python PySide6 numpy pynput websocket-client
```

### Linux / SteamOS

```bash
chmod +x setup.sh
./setup.sh
```

Or install manually:

```bash
python3 -m pip install mediapipe opencv-python PySide6 numpy pynput websocket-client
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
python main.py --profile default --autostart   # Start with a profile and auto-track
```

## Testing

Run the whole test suite (unit, synthetic PnP, UI dialogs, render pixel checks,
live settings, real-inference smoke test):

```bash
run_tests.bat
```

Each suite is a standalone script under `tests/` (exit code 0/1); screenshots
go to `tests/out/`. Requires the MediaPipe models (`setup.bat` downloads them)
and `models/` present. `test_pose_fallback.py` covers the side-view fallback
(full-circle yaw, depth-branch alignment, source switching) and needs no model.
Optionally, with pytest installed, `pytest tests/` works too.

## Usage

1. **Select camera** — Camera tab, pick a webcam, enter an IP/WebSocket URL
2. **Press Start** — Button turns yellow (⏳) then red (Stop), tracking begins
3. **Select profile** — Axes tab, pick a profile from the dropdown
4. **Launch your game** — FreeTrack/UDP data is sent automatically
5. **Press Stop** — Button turns green (Start), tracking stops, all values reset to zero

> **Tip:** the game must be (re)started **after** tracking is running, with the same
> user privileges as the tracker — FreeTrack games read the shared memory at startup.

### Live Settings

While tracking is running you can still change most settings and they apply
instantly, without restarting:

- **Axes tab** — profile selector, per-axis settings (enabled/sensitivity/deadzone/inverted), smoothing slider
- **Camera tab** — rotation, mirror, low light enhancement, camera adaptation values (position/tilt/FOV/set center)
- **Output tab (Mouse)** — mode, speed, stop method, hotkey

Only the **camera source** (local index, URL, resolution, FPS) and the **output
protocol** (FreeTrack/UDP host/port) need a restart — those stay locked while
tracking.

### UI Layout

```
┌──────────────────────────┬──────────────────────────┐
│  Camera Preview          │  Tabs                    │
│                          │  ┌────────────────────┐  │
│  Cockpit (in-game view)  │  │ Camera / Axes /    │  │
│                          │  │ Output / Log /     │  │
│  [Demo] [Tuning]         │  │ About              │  │
│  [Start] [Face: ▾]       │  └────────────────────┘  │
│  ┌───────┬─────────┐     │                          │
│  │ Pose  │  Info   │     │                          │
│  │ Y/P/R │ Conf    │     │                          │
│  │ X/Y/Z │ FPS     │     │                          │
│  └───────┴─────────┘     │                          │
└──────────────────────────┴──────────────────────────┘
```

The left column shows two stacked views at the same time. Top: the camera
preview with the face mesh, pose axes, confidence bar, current FPS, and
numbered boxes around every detected face — the tracked face is highlighted
yellow. The **Mesh detail** dropdown on the Camera tab picks the overlay
density: *contours* (face oval + lips/eyes/brows), *medium* (every 4th mesh
edge) or *full* (the complete 852-triangle mesh) — all drawn with thin 1px
lines, so even the full mesh stays cheap to render. Bottom: the **cockpit
preview** — a software-rendered in-game view
fed with the exact values sent to the game (yaw mirrored the way the game
shows it), with RAW/SENT readouts on top. When several faces are detected,
the **Face** dropdown selects which one to track (tracking stays locked to
that person even if the detection order changes). The **Demo** checkbox
drives the cockpit through the real mapping pipeline without a camera or
game, useful for checking sensitivity/curves.

### Axes Tab

The Axes tab contains:
- **Profile selector** at the top — pick a profile or create a new one
- **Per-axis settings** — Enabled, Sensitivity, Deadzone, Inverted for each of 6 axes (Yaw, Pitch, Roll, X, Y, Z)
- **Axes helper…** — opens a visual tuning dialog:
  - **Response curves** — one mini-plot per axis showing the input→output
    transfer function. Drag the white circles on the axis to set the deadzone,
    drag the curve to set the sensitivity (changes apply live). Drag the yellow
    **bend handle** to shape a nonlinear curve: it adds a second point (x2, y2)
    — the curve goes through (0,0)→(x2,y2) then continues with the sensitivity
    slope, so you can boost small movements while keeping large ones smooth.
    The yellow dot shows your current head position on the curve.
  - **Live test screen** — a 2D view of the X/Y output (with the deadzone
    square) and gauges for Yaw/Pitch/Roll: the white tick is the input, the
    green bar is the output after deadzone and sensitivity, so you can see the
    amplification and the deadzone band while moving your head. Needs tracking
    to be running.

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

For a phone used as a camera (e.g. IP Webcam, DroidCam, or the bundled HeadTrackerCam app):

1. Camera tab → Source: `WebSocket`
2. Enter URL: `ws://192.168.1.100:8080/ws` (raw MJPEG frames or JSON with a base64 image field)
3. Press Start — frames are received over WebSocket and tracked as usual

### Android Companion App (HeadTrackerCam)

The bundled `android/` project turns an Android phone into a camera for
HeadTracker. The phone runs a WebSocket server and pushes raw binary MJPEG
frames (no base64) — the desktop `WebSocketCamera` decodes them directly.
CameraX uses `STRATEGY_KEEP_ONLY_LATEST`, so the newest frame is always sent
and nothing queues up between camera and encoder: end-to-end latency is one
frame duration plus encode + network time. Frames are streamed in landscape
orientation and the stream keeps running in the background (screen off or app
minimized) — a partial wake lock keeps the phone from sleeping while the
desktop is tracking.

**Build and install** (requires Android SDK; produces `android/app/build/outputs/apk/debug/app-debug.apk`):

```bash
cd android
gradlew.bat assembleDebug      # Windows
./gradlew assembleDebug         # Linux / macOS
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

**Wi-Fi (wireless):** phone and PC on the same network (5 GHz recommended).
Open the app, press **Start stream** — the screen shows the IP, port and the
exact desktop URL (`ws://<phone-ip>:8080/ws`). Enter it in Camera tab → Source
`WebSocket` and press Start.

**USB (wired, lowest latency, no Wi-Fi needed):** enable USB debugging on the
phone (Developer options), connect the cable, confirm the RSA dialog, then in
HeadTracker pick Source **`USB Phone (HeadTrackerCam)`** on the Camera tab —
the app detects adb, sets up the port forward automatically and shows the
status right there (press **Setup USB bridge** to re-check anytime). The URL
field is locked to `ws://127.0.0.1:8080/ws`; press Start and the frames flow
over the cable. If the automatic setup cannot find adb, run the script
manually once:

| Platform | Command |
|----------|---------|
| Windows | `android_usb.bat` |
| Linux / macOS | `./android_usb.sh` |

The bridge survives replays: if the cable is unplugged, HeadTracker detects
the dead stream and reconnects automatically.

**Latency tips:** pick the lowest resolution that still tracks reliably
(640x480 is a good default — MediaPipe tracks fine at 320x240 too), lower JPEG
quality to 50 for less traffic, and use USB or 5 GHz Wi-Fi instead of 2.4 GHz.
The app shows live encoder FPS; HeadTracker shows the received FPS and frame
time in the Stream Stats panel.

### Camera Orientation

If the camera is mounted sideways or upside down:

1. Camera tab → **Rotation:** pick 90°/180°/270° until your face is upright in the preview
2. **Mirror** flips the image horizontally (selfie-style preview)

Both options are applied to the image, preview, and tracking consistently, instantly
even while tracking runs. After changing them, keep your head straight for a second:
Yaw/Pitch/Roll should read ≈ 0.

### Camera Adaptation

The camera rarely sits exactly at eye level pointing straight at your face — the
measured pose is then skewed (a camera above the monitor adds a fake pitch, a
camera off to the side adds yaw, and so on). The **Camera adaptation** group on
the Camera tab compensates the mounting geometry so the pose is expressed
relative to the monitor, like in commercial trackers:

- **Camera position (cm)** — where the camera sits relative to the monitor
  center: `X` right (+), `Y` up (+), `Z` distance from the screen toward you.
- **Camera tilt (deg)** — how the camera is aimed: `Yaw` turned sideways,
  `Pitch` (positive = looks down at the face), `Roll` tilted.
- **FOV (deg)** — horizontal field of view of your camera (webcam specs or a
  guess); `0` keeps the legacy estimate (≈53°). Correct FOV makes rotations
  and distance read accurately. Typical webcams: 60–90°.
- **Set center** — sit up straight facing the screen and press it while
  tracking: the current pose becomes the zero reference (rotation and
  position). **Reset center** clears it. Enable **Save center to profile** to
  keep the center in the current profile — it is then applied automatically
  whenever tracking starts with that profile (handy for different sitting
  positions per game); the center is otherwise per session.
- **Setup helper…** — opens a visual dialog with a 2D front view of the monitor:
  click or drag on the screen to mark where the camera sits (positions are
  measured from the screen center — clicking the center gives 0,0). The camera
  yaw/pitch are aimed at your face automatically and your distance is tuned
  during calibration. Every change is applied live to the settings, then fine
  tune in the spin boxes if needed.

All values apply live while tracking, so you can tune them by watching the
Status tab (angles should read ≈ 0 when you look straight at the screen).
Defaults (all zeros, FOV 0) keep the previous behavior exactly.

### Low Light

For dim environments, enable CLAHE image enhancement:

1. Camera tab → check `Enhance low light (CLAHE)`
2. Adaptive histogram equalization improves face detection in poor lighting
3. Applies instantly — can be toggled during tracking

### Smoothing

Axes tab → **Smoothing** slider (0–100%) controls the pose filter applied to the
whole head pose (yaw/pitch/roll and position) before it is sent to any protocol.
At higher values a small deadzone and a velocity-adaptive gain (Accela-style)
smooth out jitter, while fast deliberate moves still pass through. The rotation
is filtered in the tangent space (matrix deltas, not Euler angles), so it
stays stable when you look straight up — no gimbal jumps. Higher values feel
smoother but add lag; start around 60%. The filter is reset when the face is
lost and re-acquired, and the slider stays active during tracking — you can
tune it live.

### Output Protocols

| Protocol | Platform | Use case |
|----------|----------|----------|
| FreeTrack | Windows | 800+ sim racing/flight games via shared memory |
| UDP | All | Cross-platform network output, games that support UDP trackers |
| Mouse | All | Moves the system mouse from head pose — mouse-look in games without tracker support |

The Output tab shows a **protocol log** (updates every ~60 frames) with the raw
pose and `conf` — useful to verify tracking before launching the game.

The **Log tab** shows the app log plus a **performance graph**: live FPS,
frame time and tracking latency over the last 10 seconds. Red dashed markers
appear when the camera stalls and reconnects (e.g. after sleep), so you can see
the impact of image enhancement/resolution on performance. The status line also
shows "Camera stalled — reconnecting..." while a dead stream is being restarted.

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

Mode, speed, stop method and hotkey can all be changed while tracking runs —
they apply immediately.

Pose is smoothed by the adaptive pose filter and a small minimum deadzone is
applied so small head jitter (especially the pitch drift while turning your head
sideways) does not move the cursor unexpectedly.

> **Note:** some games read the mouse via Raw Input and ignore programmatically
> injected movement (SendInput/pynput). Such games will not respond to Mouse output;
> FreeTrack or UDP remain the reliable options there.

### Minimizing

Minimizing the window while tracking pauses tracking — the camera and
inference stop, saving CPU resources; restoring the window resumes tracking
automatically. Hiding to the system tray does **not** pause, so tracking
keeps running in the background while you play.

### Exit Confirmation

When tracking is active, closing the window shows a warning dialog: "Отслеживание активно. Вы уверены, что хотите выйти?" — prevents accidental exit.

### Localization

Language selector in the About tab. Changes apply instantly without restart:
- English, Русский, Українська, Deutsch

### Linux / macOS / SteamOS Notes

- FreeTrack shared memory is Windows-only — use **UDP output** on Linux/macOS
- Camera uses V4L2 backend (Linux) or AVFoundation (macOS)
- Face and pose (side-view fallback) models downloaded by `setup.sh`
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

Any game that supports FreeTrack or TrackIR protocol. The built-in `Default`
profile is tuned for general use (smoothing 60%, small deadzones); for a
specific game, create a profile and tune sensitivity/deadzone per axis — see
the Profile system.

### Linux / SteamOS (UDP)

Use UDP output in games that support UDP head tracking (e.g., through opentrack UDP receiver).

### Units and diagnostics

The tracker uses these units consistently throughout the processing pipeline:

- **Yaw, pitch, roll:** degrees (°).
- **X, Y, Z head translation:** millimetres (mm), produced by PnP and sent to FreeTrack/UDP.
- **Camera placement fields:** centimetres (cm) in the UI and settings; converted to millimetres internally.
- **Camera FOV:** horizontal degrees; `0` uses the legacy automatic focal-length estimate.
- **Image geometry:** pixels (px); stream rate is frames per second (FPS); frame time and tracking latency are milliseconds (ms).
- **Mouse output:** velocity mode uses pixels/second per degree, absolute mode uses pixels per degree.

The **Log** tab includes a Diagnostics block while tracking: raw PnP pose, pose after
camera calibration, mapped output pose, and the exact output state. If data is not
sent, it shows whether confidence is below `0.30`, the output is unavailable, or mouse
output is paused.

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
├── tracker.py             # MediaPipe FaceLandmarker + PnP head pose + BlazePose side-view fallback
├── android_usb.bat        # Android phone camera over USB (Windows; adb forward)
├── android_usb.sh         # Android phone camera over USB (Linux/macOS)
├── android/               # HeadTrackerCam — Android companion app (Kotlin, CameraX, WebSocket server)
├── usb_bridge.py          # adb detection + port forward for the USB phone camera
├── filter.py              # AdaptivePoseFilter (Accela-style), One Euro, Exponential, Passthrough
├── worker.py              # Background tracking thread (QThread)
├── freetrack.py           # FreeTrack 2.0 shared memory (Windows-only)
├── udp_output.py          # UDP output (cross-platform)
├── config.py              # Profile, AxisConfig, AppSettings, JSON I/O
├── ui/
│   └── main_window.py     # PySide6 GUI, overlay, profile management
├── models/                # MediaPipe face_landmarker.task + pose_landmarker_full.task (side-view fallback)
├── profiles/              # User profiles (JSON; Default built-in)
├── settings.json          # App settings (auto-saved, gitignored)
├── logs/                  # Debug session logs (gitignored)
├── THIRD_PARTY_LICENSES   # Dependency licenses
└── .gitignore
```

## Technology

| Component | Library | License |
|-----------|---------|---------|
| Face tracking | MediaPipe FaceLandmarker | Apache 2.0 |
| Side-view fallback | MediaPipe PoseLandmarker (BlazePose) | Apache 2.0 |
| Head pose | OpenCV solvePnP | Apache 2.0 |
| GUI | PySide6 | LGPL v3 |
| Camera | OpenCV | Apache 2.0 |

## License

This project uses third-party libraries with permissive licenses. See `THIRD_PARTY_LICENSES` for details.
