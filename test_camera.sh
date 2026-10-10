#!/bin/bash
# test_camera.sh - measures how smooth the camera really is, and what is slowing it down.
# Run it on the Pi while Knightscribe is running (ideally while recording):
#   bash ~/knightcribe/Knightcribe-Starter/test_camera.sh
cd "$(dirname "$0")"
echo "=== 1. Pi health ==="
echo "temperature: $(vcgencmd measure_temp)   throttled: $(vcgencmd get_throttled)   (throttled=0x0 is good)"
uptime
free -m | head -2
echo
echo "=== 2. What the camera can do at 1280x720 ==="
v4l2-ctl -d /dev/video0 --list-formats-ext 2>/dev/null | grep -A40 MJPG | grep -A3 "1280x720" | head -4
echo
echo "=== 3. Page preview rate (live picture updates over 6 seconds) ==="
python3 - <<'PY'
import os, time
live = "/dev/shm/knightscribe_live.jpg" if os.path.isdir("/dev/shm") else "live.jpg"
n, last, end = 0, None, time.time() + 6
while time.time() < end:
    try:
        m = os.stat(live).st_mtime_ns
    except OSError:
        m = None
    if m != last:
        n += 1
        last = m
    time.sleep(0.005)
n = max(0, n - 1)
print("preview updates: %d in 6 s = about %.1f per second (should be about 30)" % (n, n / 6))
PY
echo
echo "=== 4. Recorded video frame rate (newest finished segment) ==="
newest=$(ls -t lectures/*/video_*.mkv 2>/dev/null | head -2 | tail -1)
if [ -n "$newest" ] && [ "$(ls lectures/*/video_*.mkv | wc -l)" -ge 1 ]; then
  echo "file: $newest"
  ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=avg_frame_rate,nb_read_packets:format=duration -of default=nw=1 "$newest"
  echo "(frames divided by duration is the real fps; 30 is the target)"
else
  echo "no recording yet: press Record for at least 20 seconds and run this again"
fi
echo
echo "=== 5. What is using the CPU right now ==="
top -b -n2 -d2 -o %CPU | awk '/^top -/{c++} c==2' | sed -n '7,16p'
