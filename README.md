# Knightscribe

KnightScribe turns live lectures into intelligent, searchable memory by connecting what professors say, write, and show. Students can revisit key moments, recover what they missed, and turn class content into organized knowledge built for studying.

## The classroom device

Classroom lecture capture on a Raspberry Pi 4: records the lecture (720p30 video + mic audio)
and saves straightened snapshots of the board whenever the writing changes and nobody is in the
way, plus a cleaned, saturated copy that is easy to read and the text read off the board (OCR).

The web page shows live video with the teaching area outlined, lets you select that area
(drag a box, click 4 corners, or press **Auto-Find Board** to let the program find it), shows the
detector's debug view, the latest saved snapshot and the board / slide text.

The teaching area can be a whiteboard or a PowerPoint / projector screen. Pick it with the **Surface**
menu on the page, or leave it on auto: dark slides, slides with coloured areas (title bars, logos) and
slides with pictures or charts are recognised as slides. A plain white slide with only black text looks
just like neat whiteboard writing, so choose **Surface: slides** for those; its text is read either way.
Slides are saved when the picture changes, whiteboards when new writing appears.

Until you press **Start Recording** nothing is saved: the live preview still runs at 30 fps, but the
detector only looks once a second and there are no snapshots, no person check and no transcription.
If the camera drops off USB or freezes, Knightscribe reconnects by itself: the page shows
"reconnecting...", the files recorded so far are closed cleanly, and a recording carries on in a new
lecture folder as soon as the camera is back. Frequent drops mean a loose cable or a weak power supply:
plug the camera in firmly, keep its cable from being pulled, and use the official 5 V 3 A supply.

| File | What it does |
|---|---|
| `knightcribe.cpp` | Capture program (C++/OpenCV). Runs ffmpeg for recording; teaching area, board check, person check (NanoDet), snapshots, cleanup, OCR. |
| `web.py` | Device control page (Python/Flask). |
| `export.py` | Packages a finished lecture (transcript + whiteboard / slide photos with their text) into `lecture.json`, `chunks.jsonl` and `for_llm.txt`, ready to send to an LLM or a database. |
| `live_captions.py` | Live transcription (sherpa-onnx streaming model), about 1-2 s behind the speaker; saves the lecture's `transcript.jsonl`. Started by `web.py`. |
| `pi_start.sh` | Runs on the Pi: installs what's missing, downloads the person model, builds, starts. |
| `send_code.cmd` | Runs on Windows: copies the code to the Pi and runs `pi_start.sh`. |
| `test_camera.sh` | Runs on the Pi: checks temperature, preview rate, recorded frame rate and CPU use. |
| `CMakeLists.txt` | Build file for the C++ program. |

## Hardware
- Raspberry Pi 4 (4 GB) running Raspberry Pi OS / Debian 13
- USB MJPEG camera (720p30 is used) (`/dev/video0`) and a USB microphone (ALSA)
- Enough free storage: about 3.6 GB per hour of lecture

## Send to the Pi and start it (from Windows)
Double-click `send_code.cmd` and type the Pi password when asked (twice). Keep that window open;
Ctrl+C in it stops Knightscribe. Then open http://knightcribe.local:5000.

`send_code.cmd` assumes the Pi is `jvertus@knightcribe.local` with the project in
`~/knightcribe/Knightcribe-Starter`. Edit the `PI_USER`, `PI_HOST` and `PI_DIR` lines at the top of
the file if yours differ (use the Pi's IP address if `knightcribe.local` doesn't resolve).
`pi_start.sh` installs the packages it needs (g++, cmake, OpenCV, ffmpeg, v4l-utils, Flask,
Tesseract) the first time it runs.

## Running by hand on the Pi
```
cd ~/knightcribe/Knightcribe-Starter
cmake -B build -S . && cmake --build build
python3 web.py                       # the control page; it starts the capture program for you
./build/knightcribe preview          # or run the capture program alone: nothing is saved
./build/knightcribe record           # ...or record a lecture
```
The microphone, exposure and teaching area are stored in `config.json`, which the web page writes.
Set `"mic": ""` there to record without audio.

## How a snapshot gets taken
1. The board inside the teaching area has been still for 2 seconds.
2. Board check: there is writing on it (at least 0.2% of the board).
3. It differs from the last snapshot (at least 0.15% of the board).
4. Person check: NanoDet finds no person overlapping the teaching area. If someone is in the way
   the snapshot is held (orange box in the debug view) and taken as soon as they step away.
5. Saves `snap_<seconds>.jpg` (original), `snap_<seconds>_clean.jpg` (white background,
   saturated marker) and `snap_<seconds>.txt` (Tesseract OCR of the board).

For slides, steps 2 and 3 become: the screen is not blank, and over 2% of it differs from the last
saved slide. Slides are saved as they are (no cleanup), and light text on dark title bars or dark
themes is flipped before OCR so it is read too. `snapshots.csv` records the kind (`whiteboard` or
`slide`) of every snapshot.

## Output
`lectures/<date_time>/` holds `video_000.mkv, video_001.mkv…` (5-minute pieces), `audio.flac`,
`snapshots/` and `snapshots.csv` (time of each snapshot on the recording clock), `chunks/` (16 kHz
audio pieces, kept for a later, more accurate transcription off the Pi) and `transcript.jsonl` (the lecture
text with start/end times on the same clock as the video and snapshots). When the lecture is sent to the
website, `cloud.py` also joins the video and audio into `recording.mp4`.

## Live transcription
Only while a recording is running (and for a few seconds after it, to save the last sentence), `web.py`
starts `live_captions.py` in the Python virtual environment at `~/knightcribe/.venv` (`pi_start.sh` installs
sherpa-onnx there). It listens on UDP port 5005 (ffmpeg sends the microphone there while recording) and runs
a small streaming model ([sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), zipformer 20M, English) that
shows words about 1-2 seconds after they are spoken. Every finished sentence is added to the lecture's
`transcript.jsonl`; the sentence being spoken right now shows in grey on the page.

Whisper no longer runs on the Pi (it was too slow for a Pi 4). A more accurate transcript can be made later
from `recording.mp4` or the `chunks/` pieces on a faster computer or a cloud server.

## Export for LLMs and databases
When a recording has stopped (or when you press **Export Lecture Data**), `export.py` writes
`lectures/<lecture>/export/`:
- `lecture.json`: everything in one document (`knightscribe.lecture.v1`): transcript, every whiteboard / slide
  photo with its text and kind, and one merged timeline.
- `chunks.jsonl`: one JSON object per line, about 45 seconds of speech plus the board / slide text on screen
  at that time. `embedding_text` is ready to embed and insert into a vector database.
- `for_llm.txt`: the whole lecture as timestamped plain text to paste into a prompt.
All times are seconds from the start of the recording (the same clock as the video).
Run it by hand with `python3 export.py [lecture_folder_name]` (no name = the newest lecture).

## Credits
Person detection uses the NanoDet model from the
[OpenCV Model Zoo](https://github.com/opencv/opencv_zoo) (downloaded by `pi_start.sh`, not stored
in this repository). Whiteboard text is read with [Tesseract](https://github.com/tesseract-ocr/tesseract).

## License
MIT - see `LICENSE`.
