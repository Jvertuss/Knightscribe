#!/bin/bash
# pi_start.sh - runs ON THE PI (send_code.cmd starts it for you).
# Installs anything missing, gets the person-detection model, builds the C++ program, and starts
# the web page (web.py), which in turn starts and stops the C++ program.
cd ~/knightcribe/Knightcribe-Starter || exit 1

need=""
for p in g++ cmake libopencv-dev ffmpeg v4l-utils python3-flask python3-venv tesseract-ocr; do
  dpkg -s "$p" >/dev/null 2>&1 || need="$need $p"
done
if [ -n "$need" ]; then
  echo "Installing:$need  (sudo may ask for the Pi password)"
  sudo apt-get install -y $need || { sudo apt-get update && sudo apt-get install -y $need; } || exit 1
fi

# NanoDet person detector (OpenCV model zoo, 3.8 MB) - downloaded once
if [ ! -s models/nanodet.onnx ]; then
  echo "Downloading the person-detection model..."
  mkdir -p models
  # download to a temporary name first, so a failed download never leaves a broken model behind
  if wget -q -O models/nanodet.onnx.part \
      https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_detection_nanodet/object_detection_nanodet_2022nov.onnx; then
    mv models/nanodet.onnx.part models/nanodet.onnx
  else
    rm -f models/nanodet.onnx.part
    echo "WARNING: model download failed - person check will be OFF until it works"
  fi
fi

# Live transcription (faster-whisper) lives in a virtual environment next to the project folder.
# Installed once. The speech models (base.en, tiny.en) download in the background on first start.
VENV=~/knightcribe/.venv
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
if ! "$VENV/bin/python" -c "import faster_whisper" 2>/dev/null; then
  echo "Installing faster-whisper (first time only, a few minutes)..."
  "$VENV/bin/pip" install -q faster-whisper || echo "WARNING: faster-whisper install failed - live transcription will be OFF"
fi
if ! "$VENV/bin/python" -c "import sherpa_onnx" 2>/dev/null; then
  echo "Installing sherpa-onnx for instant draft captions (first time only)..."
  "$VENV/bin/pip" install -q sherpa-onnx || echo "WARNING: sherpa-onnx install failed - instant captions will be OFF"
fi
# Fetch the speech models now (only if missing) so starting a recording never waits on the internet.
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import faster_whisper" 2>/dev/null; then
  echo "Checking the speech models (first time downloads about 350 MB)..."
  "$VENV/bin/python" -c "
from faster_whisper.utils import download_model
for name in ('base.en', 'tiny.en'):
    download_model(name)
" || echo "WARNING: could not download the Whisper models - they will be fetched when a recording starts"
  "$VENV/bin/python" -c "import live_captions; live_captions.ensure_model()" \
    || echo "WARNING: could not download the live-captions model - it will be fetched when a recording starts"
fi

# Stop any copy of Knightscribe that is already running (frees the camera and port 5000).
# web.py closes a running recording cleanly when it is stopped, so give it up to 30 s.
pkill -f "[p]ython3 web.py"
for i in $(seq 30); do pgrep -f "[b]uild/knightcribe" >/dev/null || break; sleep 1; done
pkill -INT -f "[b]uild/knightcribe"; sleep 2
pkill -f "[t]ranscribe.py"; pkill -f "[l]ive_captions.py"
pkill -f "[f]fmpeg .*-f v4l2"   # a leftover ffmpeg would keep the camera busy
sleep 1

echo "Building..."
cmake -B build -S . >/dev/null && cmake --build build || { echo "BUILD FAILED"; exit 1; }

echo
echo "=== Knightscribe is running: open http://knightcribe.local:5000  (Ctrl+C here to stop) ==="
python3 web.py
