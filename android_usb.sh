#!/bin/sh
# HeadTracker - USB camera bridge for the Android companion app (HeadTrackerCam).
# Forwards the phone's WebSocket port to this PC, so HeadTracker can use
# the phone camera over USB without Wi-Fi (only USB debugging is needed).
PORT=8080

ADB=$(command -v adb 2>/dev/null)
if [ -z "$ADB" ]; then
    if [ -n "$ANDROID_HOME" ]; then
        ADB="$ANDROID_HOME/platform-tools/adb"
    else
        ADB="$HOME/Android/Sdk/platform-tools/adb"
    fi
fi

if [ ! -x "$ADB" ]; then
    echo "adb not found in PATH, \$ANDROID_HOME or ~/Android/Sdk."
    echo "Install Android platform-tools (or Android Studio), then re-run this script."
    exit 1
fi

echo "Checking connected devices..."
"$ADB" devices

"$ADB" forward tcp:$PORT tcp:$PORT
if [ $? -ne 0 ]; then
    echo
    echo "Failed to set up USB forwarding."
    echo "Make sure: USB debugging is enabled on the phone (Developer options),"
    echo "the phone is connected via cable, and you confirmed the RSA dialog."
    exit 1
fi

echo
echo "============================================================"
echo "  USB bridge ready: the phone's port $PORT is now local."
echo
echo "  In HeadTracker:  Camera tab - Source \"WebSocket\""
echo "  URL:             ws://127.0.0.1:$PORT/ws"
echo
echo "  Start the stream in the phone app, then press Start."
echo "  To remove the forward later: adb forward --remove tcp:$PORT"
echo "============================================================"
exit 0