# web.py - Knightscribe device control page.  Run:  python3 web.py   then open http://knightcribe.local:5000
# Keeps the C++ program running (preview mode normally, record mode during a lecture), streams the
# live video, lets you select the teaching area (drag a box or click 4 corners), shows the detector's
# debug view, the latest saved snapshot (original or cleaned) and the whiteboard text it read.
# It talks to the C++ program only through files: config.json (settings, written here, read there)
# and status.json / debug.jpg / live.jpg (written there, read here).
import glob, json, logging, os, re, shutil, signal, subprocess, sys, threading, time
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
path = lambda name: os.path.join(HERE, name)
LECTURES = path("lectures")
DEFAULTS = {"corners": [], "exposure": 0, "mic": "plughw:CARD=Microphone", "surface": "auto"}
# live transcription runs in the venv that has faster-whisper installed (pi_start.sh sets it up)
VENV_PYTHON = os.path.join(HERE, "..", ".venv", "bin", "python")
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.WARNING)  # don't print every page refresh
proc, mode, lock = None, "preview", threading.Lock()
last_launch = 0.0  # when the C++ program was last started
# helper programs that run in the venv: name -> [process, when we last tried to start it]
helpers = {"transcribe.py": [None, 0], "live_captions.py": [None, 0]}
LIVE_JPG = "/dev/shm/knightscribe_live.jpg" if os.path.isdir("/dev/shm") else path("live.jpg")  # knightcribe.cpp writes it
STREAM_FPS = 30  # lower this (e.g. 15) if the Wi-Fi link to the page can not carry the live video
LIVE = "/dev/shm/knightcribe_live.json" if os.path.isdir("/dev/shm") else path("live.json")  # live_captions.py writes it


def load():
    try:
        return {**DEFAULTS, **json.load(open(path("config.json")))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(changes):  # write the whole file then swap it in, so C++ never reads half of it
    cfg = {**load(), **changes}
    with open(path("config.json.tmp"), "w") as f:
        json.dump(cfg, f)
    os.replace(path("config.json.tmp"), path("config.json"))


def running():  # is the C++ program alive right now?
    return proc is not None and proc.poll() is None


def group_alive(pgid):  # is any process of this group (the C++ program, its ffmpeg) still there?
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_leftover_ffmpeg():  # an ffmpeg left behind by a capture program that was killed keeps the camera busy
    try:
        pid = int(open(path("ffmpeg.pid")).read())
        if b"ffmpeg" not in open("/proc/%d/cmdline" % pid, "rb").read():
            return
    except (OSError, ValueError):
        return
    # it was already told to stop when its program died: give it 10 s to close its files, then force it
    for _ in range(100):
        if not os.path.exists("/proc/%d" % pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def stop_program():  # Ctrl+C to the program, which passes it on to its ffmpeg so the recording files close cleanly
    if proc is None:
        return
    if proc.poll() is not None:  # it ended by itself: make sure its ffmpeg is gone too (it would keep the camera busy)
        if group_alive(proc.pid):
            os.killpg(proc.pid, signal.SIGINT)
            for _ in range(100):  # up to 10 s to close its files
                if not group_alive(proc.pid):
                    return
                time.sleep(0.1)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stop_leftover_ffmpeg()
        return
    # Ctrl+C, repeated after 3 s and 8 s: a program that has only just started can miss the first one (it is
    # deaf to Ctrl+C while it sets up the camera). ffmpeg still closes its files cleanly after a third one.
    for wait in (3, 5, 22):
        try:
            os.killpg(proc.pid, signal.SIGINT)
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue
        except ProcessLookupError:
            proc.wait()
            return
    try:  # ffmpeg is stuck: force it so the page can't hang forever
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()
    stop_leftover_ffmpeg()


def ensure_helpers():  # keep the transcription helpers running (retry each at most every 10 s)
    for name, entry in helpers.items():
        proc_, tried = entry
        if (proc_ and proc_.poll() is None) or time.time() - tried < 10:
            continue
        entry[1] = time.time()
        if os.path.exists(VENV_PYTHON) and os.path.exists(path(name)):
            entry[0] = subprocess.Popen([VENV_PYTHON, path(name)], cwd=HERE, start_new_session=True)


last_recording = 0.0  # when a recording was last running
export_pending = None  # the lecture to package once its transcript is complete


def newest_lecture():  # lecture folders are named after their start time, so the newest sorts last
    try:
        names = [n for n in os.listdir(LECTURES) if re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d", n)]
        return max(names) if names else None
    except OSError:
        return None


def export_lecture(name):  # package a lecture for an LLM / database (export.py writes lectures/<name>/export/)
    result = subprocess.run([sys.executable, path("export.py"), name], capture_output=True, text=True, timeout=60)
    return result.returncode == 0, (result.stdout or result.stderr).strip()


def stop_helpers():
    for entry in helpers.values():
        if entry[0] and entry[0].poll() is None:
            os.killpg(entry[0].pid, signal.SIGTERM)
        entry[0], entry[1] = None, 0  # ready to start again with the next recording


def manage_helpers(recording):  # speech helpers run only for a recording, plus the time to finish its last pieces
    global last_recording, export_pending
    now = time.time()
    if recording:
        last_recording = now
        export_pending = newest_lecture()
        ensure_helpers()
        return
    if now - last_recording < 40:
        return  # the last audio pieces and grey draft captions are still being finished
    if any(helper_running(name) for name in helpers):
        try:
            with open(path("transcribe_status.json")) as f:
                tx = json.load(f)
        except (OSError, ValueError):
            tx = {}
        if not ((tx.get("state") == "idle" and not tx.get("backlog")) or now - last_recording > 600):
            return  # Whisper is still working through the last pieces
        stop_helpers()  # frees the memory and CPU that Whisper and the live captions were using
    if export_pending:  # the transcript is complete now: package the lecture automatically
        name, export_pending = export_pending, None
        try:
            export_lecture(name)
        except (OSError, subprocess.SubprocessError):
            pass


def supervise():  # runs in the background, whether or not anyone has the page open
    quick_failures = 0  # times in a row the program stopped within 20 s of starting
    while True:
        time.sleep(1)
        try:
            with lock:
                died = proc is not None and proc.poll() is not None
                ran = time.time() - last_launch
            if died and ran > 2:
                # The capture program stopped by itself (the camera's USB link dropped, a crash). Start it again
                # right away. If a lecture was being recorded, keep recording (into a new lecture folder; the
                # files recorded so far stay saved), unless it failed at once 3 times in a row (then preview).
                quick_failures = quick_failures + 1 if ran < 20 else 0
                again = "record" if mode == "record" and quick_failures < 3 else "preview"
                print("capture program stopped (exit code %s) - starting it again (%s)" % (proc.returncode, again), flush=True)
                launch(again)
            manage_helpers(mode == "record" and running())
        except Exception as error:  # the supervisor must never stop
            print("supervisor:", error, flush=True)


def helper_running(name):
    return bool(helpers[name][0] and helpers[name][0].poll() is None)


def transcript_tail(lecture, count=40):  # last lines of the lecture's transcript, newest last
    try:
        with open(os.path.join(LECTURES, lecture, "transcript.jsonl")) as f:
            return [json.loads(line) for line in f.read().splitlines()[-count:] if line.strip()]
    except (OSError, ValueError):
        return []


def launch(new_mode):  # stop whatever is running, then start the C++ program in new_mode
    global proc, mode, last_launch
    with lock:
        last_launch = time.time()
        stop_program()
        proc, mode = subprocess.Popen([path("build/knightcribe"), new_mode], cwd=HERE,
                                      start_new_session=True), new_mode


def latest_snapshot():  # (lecture folder, newest snapshot name) of the newest lecture
    try:
        lec = newest_lecture()
        if not lec:
            return None, []
        snaps = sorted(f[:-4] for f in os.listdir(os.path.join(LECTURES, lec, "snapshots"))
                       if f.endswith(".jpg") and not f.endswith("_clean.jpg"))
        return lec, snaps
    except (OSError, ValueError):
        return None, []


_system = {"time": 0, "data": {}}


def system():  # Pi health; recomputed at most every 5 s (vcgencmd starts a new process each time)
    if time.time() - _system["time"] < 5:
        return camera_state(_system["data"])
    s = {}
    try:
        s["temp_c"] = round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000, 1)
    except (OSError, ValueError):
        s["temp_c"] = None
    try:
        s["throttled"] = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True,
                                        timeout=2).stdout.strip().split("=")[-1] or None
    except (OSError, subprocess.TimeoutExpired):
        s["throttled"] = None
    s["load"] = round(os.getloadavg()[0], 2)
    free = shutil.disk_usage(HERE).free / 1e9
    s["disk_free_gb"], s["hours_left"] = round(free, 1), round(free / 3.6, 1)  # 8 Mbit/s video ~ 3.6 GB/hour
    _system.update(time=time.time(), data=s)
    return camera_state(s)


def camera_state(s):  # checked on every request (cheap), so the page notices a dropped camera at once
    s = dict(s)
    try:
        s["camera_ok"] = time.time() - os.path.getmtime(LIVE_JPG) < 3
    except OSError:
        s["camera_ok"] = False
    s["camera_plugged"] = bool(glob.glob("/dev/v4l/by-id/*-video-index0") or os.path.exists("/dev/video0"))
    return s


@app.get("/")
def index():
    return PAGE


@app.get("/video")
def video():  # live video: sends the newest picture every time ffmpeg replaces it (up to STREAM_FPS a second)
    def frames():
        last, sent = None, 0.0
        while True:
            try:
                stamp = os.stat(LIVE_JPG).st_mtime_ns
                # 0.8: a picture that arrives a little early is still sent (an exact 1/STREAM_FPS limit
                # would beat against the camera's own timing and drop about every fifth picture)
                if stamp != last and time.time() - sent >= 0.8 / STREAM_FPS:
                    last, sent = stamp, time.time()
                    with open(LIVE_JPG, "rb") as f:
                        data = f.read()
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            except OSError:
                pass
            time.sleep(0.005)
    return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/detector/image")
def detector_image():
    return send_file(path("debug.jpg"), max_age=0) if os.path.exists(path("debug.jpg")) else ("", 404)


@app.get("/snapshot/latest")
def snapshot_latest():
    lec, snaps = latest_snapshot()
    if not snaps:
        return "", 404
    name = snaps[-1] + ("_clean.jpg" if request.args.get("clean") == "1" else ".jpg")
    return send_from_directory(os.path.join(LECTURES, lec, "snapshots"), name, max_age=0)


@app.get("/lectures/<path:p>")
def lecture_file(p):
    return send_from_directory(LECTURES, p, max_age=0)


@app.get("/status")
def status():
    try:
        with open(path("status.json")) as f:
            det = json.load(f)
    except (OSError, ValueError):
        det = {"state": "starting", "recording": False}
    lec, snaps = latest_snapshot()
    text = None
    if snaps:
        try:
            with open(os.path.join(LECTURES, lec, "snapshots", snaps[-1] + ".txt")) as f:
                text = f.read().strip()
        except OSError:
            text = "" if det.get("ocr") else None
    try:
        with open(path("transcribe_status.json")) as f:
            tx = json.load(f)
    except (OSError, ValueError):
        tx = None
    tx_on = helper_running("transcribe.py") and bool(tx)
    return jsonify(detector=det, recording=mode == "record" and running(), running=running(),
                   config=load(), system=system(), lecture=lec, snaps=snaps, text=text,
                   transcription=tx if tx_on else None, transcript=transcript_tail(lec) if lec else [],
                   speech_ready=os.path.exists(VENV_PYTHON))


@app.get("/live")
def live():  # instant draft captions (written ~4 times a second by live_captions.py)
    try:
        with open(LIVE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data["running"] = helper_running("live_captions.py")
    data["fresh"] = data["running"] and time.time() - data.get("updated", 0) < 4
    return jsonify(data)


@app.post("/record/start")
def start_recording():
    if mode == "record" and running():  # a double click must not end the lecture and start a new one
        return jsonify(message="Already recording.")
    launch("record")
    return jsonify(message="Recording started.")


@app.post("/record/stop")
def stop_recording():
    if not (mode == "record" and running()):
        return jsonify(message="Not recording.")
    launch("preview")
    return jsonify(message="Recording stopped and saved.")


@app.post("/detector/area")
def detector_area():
    pts = (request.get_json(silent=True) or {}).get("points")
    if not isinstance(pts, list) or len(pts) != 4:
        return jsonify(message="Need exactly 4 corner points."), 400
    try:
        xs, ys = [min(1, max(0, float(p[0]))) for p in pts], [min(1, max(0, float(p[1]))) for p in pts]
    except (TypeError, ValueError, IndexError, KeyError):
        return jsonify(message="Corner points must be [x, y] numbers."), 400
    if max(xs) - min(xs) < 0.02 or max(ys) - min(ys) < 0.02:
        return jsonify(message="Teaching area is too small."), 400
    pts = list(zip(xs, ys))  # put clicks in TL, TR, BR, BL order (same rule as the C++ program)
    order = [min(pts, key=lambda q: q[0] + q[1]), min(pts, key=lambda q: q[1] - q[0]),
             max(pts, key=lambda q: q[0] + q[1]), max(pts, key=lambda q: q[1] - q[0])]
    save({"corners": [v for xy in order for v in xy]})
    return jsonify(message="Teaching area selected.")


@app.post("/detector/auto")
def detector_auto():  # the C++ program looks for the board in its next picture and writes autoselect.json
    if not running():
        return jsonify(message="The capture program is not running."), 503
    try:
        os.remove(path("autoselect.json"))
    except OSError:
        pass
    open(path("autoselect.request"), "w").close()
    return jsonify(message="Looking for the board...")


@app.get("/detector/auto")
def detector_auto_result():
    if os.path.exists(path("autoselect.request")):
        return jsonify(state="waiting")
    try:
        with open(path("autoselect.json")) as f:
            found = json.load(f)
    except (OSError, ValueError):
        return jsonify(state="waiting")
    pts = found.get("points") or []
    if not found.get("found") or len(pts) != 8:
        return jsonify(state="failed", message="Could not find the board. Select the teaching area by hand instead.")
    save({"corners": [min(1, max(0, float(v))) for v in pts]})
    try:
        os.remove(path("autoselect.json"))
    except OSError:
        pass
    return jsonify(state="found", message="Board found and selected. Check the outline and adjust it if needed.")


@app.post("/detector/surface")
def detector_surface():
    value = (request.get_json(silent=True) or {}).get("surface")
    if value not in ("auto", "whiteboard", "slides"):
        return jsonify(message="Surface must be auto, whiteboard or slides."), 400
    save({"surface": value})
    return jsonify(message={"auto": "Surface: the program decides between whiteboard and slides.",
                            "whiteboard": "Surface: whiteboard.",
                            "slides": "Surface: slides / projector."}[value])


@app.post("/export/latest")
def export_latest():
    name = newest_lecture()
    if not name:
        return jsonify(message="No lecture recorded yet."), 404
    try:
        ok, text = export_lecture(name)
    except (OSError, subprocess.SubprocessError) as error:
        return jsonify(message="Export failed: " + str(error)), 500
    if not ok:
        return jsonify(message="Export failed: " + text[-200:]), 500
    base = "/lectures/" + name + "/export/"
    return jsonify(message="Exported " + name + ". Files: " + base + "lecture.json, " + base + "chunks.jsonl, " + base + "for_llm.txt")


@app.post("/detector/area/clear")
def detector_area_clear():
    save({"corners": []})
    return jsonify(message="Teaching area cleared.")


@app.post("/camera/exposure")
def camera_exposure():
    data = request.get_json(silent=True) or {}
    try:
        value = 0 if data.get("mode") == "auto" else min(5000, max(1, int(data.get("value", 150))))
    except (TypeError, ValueError):
        return jsonify(message="Exposure must be a number."), 400
    save({"exposure": value})
    return jsonify(message="Exposure: " + ("auto" if value == 0 else f"manual {value / 10:.1f} ms"))


PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knightscribe</title>
<style>
    body { margin: 0; background: #111; color: #f5f5f5; font-family: system-ui, sans-serif; }
    main { max-width: 1100px; margin: auto; padding: 28px 16px; }
    .camera-wrap { position: relative; width: 100%; }
    .camera { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 14px; display: block;
              user-select: none; -webkit-user-drag: none; touch-action: none; }
    #roi-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
    #roi-poly { fill: rgba(0, 255, 102, 0.08); stroke: #00ff66; stroke-width: 3; }
    .controls, .exposure { display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; align-items: center; }
    .exposure select, .exposure input { font-size: 16px; }
    button { padding: 12px 18px; font-size: 16px; cursor: pointer; }
    #start.on { background: #c62828; color: #fff; }
    .detector { margin-top: 32px; }
    .detector-image { width: 100%; background: #000; border-radius: 14px; display: block; margin-top: 12px; }
    .info { font-size: 17px; line-height: 1.6; }
    .diag { font-family: ui-monospace, monospace; font-size: 15px; line-height: 1.6;
            background: #1b1b1b; padding: 12px 16px; border-radius: 10px; margin-top: 16px; }
    .bad { color: #ff6b6b; } .ok { color: #7dff9b; } .warn { color: #ffd166; } .dim { color: #aaa; }
    #saved-image { display: none; }
    #ocr { white-space: pre-wrap; font-size: 17px; background: #1b1b1b; padding: 12px 16px; border-radius: 10px; }
    #transcript .draft { color: #9aa0a6; }
    #transcript { font-size: 17px; background: #1b1b1b; padding: 12px 16px; border-radius: 10px;
                  max-height: 320px; overflow-y: auto; }
    #strip { display: flex; gap: 8px; overflow-x: auto; margin-top: 12px; }
    #strip img { height: 90px; border-radius: 6px; background: #fff; }
</style>
</head>
<body>
<main>
    <h1>Knightscribe</h1>
    <p class="dim">Raspberry Pi classroom capture &mdash; device control page</p>

    <div id="camera-wrap" class="camera-wrap">
        <img id="live-camera" class="camera" src="/video" alt="Knightscribe live camera preview" draggable="false">
        <svg id="roi-svg" viewBox="0 0 1 1" preserveAspectRatio="none">
            <polygon id="roi-poly" points="" vector-effect="non-scaling-stroke"></polygon>
            <g id="roi-dots"></g>
        </svg>
    </div>

    <div class="controls">
        <button id="start">Start Recording</button>
        <button id="select-area">Select Teaching Area</button>
        <button id="auto-area">Auto-Find Board</button>
        <button id="select-corners">Select 4 Corners</button>
        <button id="clear-area">Clear Area</button>
        <select id="surface" title="What is the teaching area showing?">
            <option value="auto">Surface: auto</option>
            <option value="whiteboard">Surface: whiteboard</option>
            <option value="slides">Surface: slides / projector</option>
        </select>
        <button id="export">Export Lecture Data</button>
    </div>

    <div class="exposure">
        <label>Exposure:
            <select id="exp-mode"><option value="auto">Auto</option><option value="manual">Manual</option></select>
        </label>
        <input id="exp-value" type="range" min="1" max="333" value="150">
        <span id="exp-text"></span>
        <button id="exp-apply">Apply Exposure</button>
        <span class="dim">Use Manual if a projector/TV screen looks washed out.</span>
    </div>

    <p id="status">Ready. Nothing is saved until you press Start Recording.</p>
    <div class="diag" id="diag">Loading status&hellip;</div>
    <div class="diag bad" id="errors" style="display:none"></div>

    <section class="detector">
        <h2>Visual Detector</h2>
        <div class="info">
            <div id="detector-state">State: waiting</div>
            <div id="motion">Motion: 0.000%</div>
            <div id="change">Change vs last snapshot: 0.000%</div>
            <div id="saved-count">Saved snapshots: 0</div>
        </div>
        <p class="dim">Debug view (teaching area only): red = moving now. Once the area has been
           still for a few seconds: green = new content, blue = removed content (vs last snapshot),
           orange box = person in the way (held, not saved).</p>
        <img id="detector-image" class="detector-image" alt="Detector view" draggable="false">

        <h2>Latest Saved Snapshot</h2>
        <label><input type="checkbox" id="show-clean" checked> Show cleaned-up version
            <span class="dim">(white background, saturated marker; original is always saved too)</span></label>
        <img id="saved-image" class="detector-image" alt="Latest saved teaching snapshot" draggable="false">
        <p id="no-saved" class="dim">No snapshots yet. They are only saved while recording.</p>

        <h2>Board / Slide Text</h2>
        <div id="ocr" class="dim">Appears here after the first snapshot.</div>

        <h2>Live Transcript</h2>
        <div id="tx-info" class="dim"></div>
        <div id="transcript" class="dim">Appears here while a lecture is recording.</div>

        <h2 id="strip-title">Snapshots</h2>
        <div id="strip"></div>
    </section>
</main>

<script>
const $ = id => document.getElementById(id);
const statusText = $("status"), cameraWrap = $("camera-wrap"), liveCamera = $("live-camera");
let selecting = false, dragging = false, startX = 0, startY = 0, cornerMode = false, cornerPts = [];
let st = null, lastSaved = null, stripKey = "", exposureLoaded = false, live = null, cameraWasDown = false;

function showPoly(points) {
    $("roi-poly").setAttribute("points", points && points.length ? points.map(p => p[0] + "," + p[1]).join(" ") : "");
}
function showDots(points) {
    $("roi-dots").innerHTML = points.map(p => '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="0.008" fill="#ffd166"></circle>').join("");
}
const rectPoints = (x1, y1, x2, y2) => [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
const span = (text, cls) => '<span class="' + cls + '">' + text + "</span>";
function clock(seconds) {
    const s = Math.floor(seconds), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, r = s % 60;
    return h + ":" + String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
}

async function post(url, body) {
    const options = { method: "POST" };
    if (body) { options.headers = { "Content-Type": "application/json" }; options.body = JSON.stringify(body); }
    try {
        const response = await fetch(url, options), data = await response.json();
        statusText.textContent = data.message;
        statusText.className = response.ok ? "" : "bad";
    } catch (error) {
        statusText.textContent = "Request failed: " + error;
        statusText.className = "bad";
    }
    updateStatus();
}

$("start").addEventListener("click", () => {
    const recording = st && st.recording;
    statusText.textContent = recording ? "Stopping and finalizing..." : "Starting recording...";
    post(recording ? "/record/stop" : "/record/start");
});

function showExposureText() {
    const auto = $("exp-mode").value === "auto";
    $("exp-text").textContent = auto ? "" : ($("exp-value").value / 10).toFixed(1) + " ms";
    $("exp-value").style.display = auto ? "none" : "";
}
$("exp-mode").addEventListener("change", showExposureText);
$("exp-value").addEventListener("input", showExposureText);
$("exp-apply").addEventListener("click", () => post("/camera/exposure", { mode: $("exp-mode").value, value: +$("exp-value").value }));

$("select-corners").addEventListener("click", () => {
    selecting = false; cornerMode = true; cornerPts = [];
    showPoly([]); showDots([]);
    statusText.className = "";
    statusText.textContent = "Click the 4 corners of the board on the camera image (any order).";
    $("select-corners").textContent = "Click 4 Corners...";
});
$("select-area").addEventListener("click", () => {
    cornerMode = false; selecting = true;
    statusText.textContent = "Drag a box around the TV, projector, or board.";
    $("select-area").textContent = "Drag Area On Camera";
});
$("auto-area").addEventListener("click", async () => {
    statusText.className = "";
    statusText.textContent = "Looking for the board...";
    try {
        await fetch("/detector/auto", { method: "POST" });
        for (let i = 0; i < 12; i++) {  // the capture program answers within a few seconds
            await new Promise(r => setTimeout(r, 1000));
            const r = await (await fetch("/detector/auto")).json();
            if (r.state !== "waiting") {
                statusText.textContent = r.message;
                statusText.className = r.state === "found" ? "" : "bad";
                return;
            }
        }
        statusText.textContent = "No answer from the capture program. Is it running?";
        statusText.className = "bad";
    } catch (error) {
        statusText.textContent = "Request failed: " + error;
        statusText.className = "bad";
    }
});
$("surface").addEventListener("change", () => post("/detector/surface", { surface: $("surface").value }));
$("export").addEventListener("click", () => post("/export/latest"));
$("clear-area").addEventListener("click", () => { showPoly([]); showDots([]); post("/detector/area/clear"); });
$("show-clean").addEventListener("change", () => { if (lastSaved) loadSaved(); });
liveCamera.addEventListener("dragstart", event => event.preventDefault());

function getPoint(event) {
    const rect = liveCamera.getBoundingClientRect();
    return { x: Math.max(0, Math.min(event.clientX - rect.left, rect.width)) / rect.width,
             y: Math.max(0, Math.min(event.clientY - rect.top, rect.height)) / rect.height,
             w: rect.width, h: rect.height };
}
cameraWrap.addEventListener("pointerdown", event => {
    if (cornerMode) {
        event.preventDefault();
        const p = getPoint(event);
        cornerPts.push([p.x, p.y]);
        showPoly(cornerPts); showDots(cornerPts);
        if (cornerPts.length < 4) { statusText.textContent = "Corner " + cornerPts.length + " of 4 set."; return; }
        cornerMode = false;
        $("select-corners").textContent = "Select 4 Corners";
        showDots([]);
        post("/detector/area", { points: cornerPts });
        return;
    }
    if (!selecting) return;
    event.preventDefault();
    const p = getPoint(event);
    startX = p.x; startY = p.y; dragging = true;
    cameraWrap.setPointerCapture(event.pointerId);
    showPoly([]);
});
cameraWrap.addEventListener("pointermove", event => {
    if (!dragging) return;
    const p = getPoint(event);
    showPoly(rectPoints(startX, startY, p.x, p.y));
});
cameraWrap.addEventListener("pointerup", event => {
    if (!dragging) return;
    dragging = false; selecting = false;
    $("select-area").textContent = "Select Teaching Area";
    const p = getPoint(event);
    if (Math.abs(p.x - startX) * p.w < 20 || Math.abs(p.y - startY) * p.h < 20) {
        showPoly([]); statusText.textContent = "Selection was too small."; return;
    }
    post("/detector/area", { points: rectPoints(Math.min(startX, p.x), Math.min(startY, p.y), Math.max(startX, p.x), Math.max(startY, p.y)) });
});

$("saved-image").addEventListener("error", () => { lastSaved = null; });  // not written yet: retry next poll
function loadSaved() {
    $("saved-image").src = "/snapshot/latest?t=" + Date.now() + ($("show-clean").checked ? "&clean=1" : "");
}

const esc = t => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
// Whisper's lines are white. Grey draft lines (instant, less accurate) fill the time Whisper has not reached yet.
function renderTranscript() {
    if (!st) return;
    const box = $("transcript"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
    const tx = st.transcription, covered = tx && tx.lecture === st.lecture ? (tx.covered_until || 0) : 0;
    const row = (start, text, cls) => '<div class="' + cls + '">[' + clock(start).slice(2) + "] " + esc(text) + "</div>";
    let html = st.transcript.map(l => row(l.start, l.text, "")).join("");
    if (live && live.fresh) {  // draft sentences Whisper has not covered yet (kept a while after Stop too)
        html += (live.finals || []).filter(l => l.end > covered).map(l => row(l.start, l.text, "draft")).join("");
        if (live.partial && live.state === "listening") html += row(live.partial_start || live.t || 0, live.partial, "draft");
    }
    box.innerHTML = html || '<div class="dim">' + (st.recording ? "Listening..." : "Appears here while a lecture is recording.") + "</div>";
    if (atEnd) box.scrollTop = box.scrollHeight;
}
async function pollLive() {  // draft captions refresh faster than the rest of the page
    try { live = await (await fetch("/live")).json(); } catch (error) { live = null; }
    renderTranscript();
}

async function updateStatus() {
    try { st = await (await fetch("/status")).json(); }
    catch (error) { $("diag").innerHTML = span("Knightscribe server unreachable", "bad"); return; }
    const det = st.detector, sys = st.system, cfg = st.config, errors = [];

    if (sys.camera_ok && cameraWasDown) liveCamera.src = "/video?t=" + Date.now();  // camera is back: reconnect the video
    cameraWasDown = !sys.camera_ok;
    $("start").textContent = st.recording ? "Stop Recording" : "Start Recording";
    $("start").className = st.recording ? "on" : "";
    const lines = [
        "Camera: " + (sys.camera_ok ? span("Connected", "ok")
                      : span("reconnecting...", "warn")),
        "Mode: " + (det.width ? det.width + "x" + det.height + " MJPEG @ " + det.camera_fps + " fps" +
            "" : "starting...") + " &nbsp;Exposure: " + (cfg.exposure ? "manual " + (cfg.exposure / 10).toFixed(1) + " ms" : "auto") +
            (cfg.corners.length ? " &nbsp;Teaching area: set" : " &nbsp;Teaching area: " + span("not set", "warn")) +
            (det.surface ? " &nbsp;Looks like: " + det.surface : ""),
        "Recording: " + (st.recording ? span("Yes", "ok") + " &mdash; " + det.lecture + " (" + clock(det.seconds || 0) + ")"
                                      : "No " + span("(nothing is saved while not recording)", "dim")),
        "Encoder: h264_v4l2m2m (hardware) @ 8M &nbsp;Audio: " + (cfg.mic ? cfg.mic : "off"),
        "Disk: " + sys.disk_free_gb + " GB free (~" + sys.hours_left + " h of video)",
        "Pi: " + (sys.temp_c ?? "?") + " &deg;C &nbsp;throttled " + (sys.throttled ?? "?") + " &nbsp;load " + sys.load,
        "Detector: " + det.state + (det.ms != null ? " (" + det.ms + " ms/check)" : "") +
            " &nbsp;occlusions rejected " + (det.occlusions ?? 0) +
            " &nbsp;person model " + (det.person_model ? span("on", "ok") : span("MISSING", "bad")) +
            " &nbsp;OCR " + (det.ocr ? span("on", "ok") : span("off", "warn")) +
            (det.errors ? " &nbsp;" + span(det.errors + " frame errors (recording continues)", "warn") : ""),
    ];
    const tx = st.transcription;
    lines.push("Transcription: " + (tx ? span(tx.model, "ok") + (tx.rtf != null ? " &nbsp;" + tx.rtf + "x real time" : "") +
               " &nbsp;audio pieces on disk " + (tx.on_disk ?? "?") + " &nbsp;waiting chunks " + tx.backlog + " &nbsp;" + tx.state +
                    (tx.errors ? " &nbsp;" + span(tx.errors + " chunk errors: " + tx.last_error, "bad") : "")
                    : !st.speech_ready ? span("off (faster-whisper not installed - run send_code.cmd)", "warn")
                    : st.recording ? span("starting...", "warn")
                    : span("off (starts when you press Start Recording)", "ok")));
    lines.push("Live captions: " + (live && live.fresh ? span("on", "ok") + (live.rtf != null ? " &nbsp;" + live.rtf + "x real time" : "") + " &nbsp;" + live.state
               : live && live.running && live.state ? span("starting: " + live.state, "warn")
               : !st.speech_ready ? span("off (sherpa-onnx is not installed - run send_code.cmd)", "warn")
               : st.recording ? span("starting...", "warn")
               : span("off (starts when you press Start Recording)", "ok")));
    $("diag").innerHTML = lines.join("<br>");

    if (!st.running) errors.push("The capture program is not running (check the terminal on the Pi). Restart it with send_code.cmd.");
    if (det.person_model === false) errors.push("Person model missing: models/nanodet.onnx (run send_code.cmd again to download it)");
    if (sys.throttled && sys.throttled !== "0x0") errors.push("Pi throttling/undervoltage flags: " + sys.throttled);
    if (sys.disk_free_gb < 3) errors.push("Disk space low: " + sys.disk_free_gb + " GB");
    $("errors").style.display = errors.length ? "block" : "none";
    $("errors").innerHTML = errors.join("<br>");

    $("detector-state").textContent = "State: " + det.state;
    $("motion").textContent = "Motion: " + (det.motion || 0).toFixed(3) + "%";
    $("change").textContent = "Change vs last snapshot: " + (det.change || 0).toFixed(3) + "%";
    $("saved-count").textContent = "Saved snapshots: " + (det.saved || 0) + (st.recording ? "" : " (not recording)");
    if (!dragging && !cornerMode) {
        const c = cfg.corners;
        showPoly(c.length === 8 ? [[c[0], c[1]], [c[2], c[3]], [c[4], c[5]], [c[6], c[7]]] : []);
    }
    if (!exposureLoaded) {
        exposureLoaded = true;
        if (document.activeElement !== $("surface")) $("surface").value = cfg.surface || "auto";
        $("exp-mode").value = cfg.exposure ? "manual" : "auto";
        if (cfg.exposure) $("exp-value").value = cfg.exposure;
        showExposureText();
    }
    $("detector-image").src = "/detector/image?t=" + Date.now();

    const newest = st.snaps.length ? st.lecture + "/" + st.snaps[st.snaps.length - 1] : null;
    $("saved-image").style.display = newest ? "block" : "none";
    $("no-saved").style.display = newest ? "none" : "block";
    if (newest !== lastSaved) { lastSaved = newest; if (newest) loadSaved(); }
    $("ocr").textContent = st.text === null ? (det.ocr === false ? "OCR is off (tesseract not installed)." : "Appears here after the first snapshot.")
                                            : (st.text || "(reading the board...)");
    $("ocr").className = st.text ? "" : "dim";

    renderTranscript();
    $("tx-info").textContent = tx && tx.backlog > 2 ? "Catching up: " + tx.backlog + " audio pieces waiting." : "";

    const key = st.lecture + st.snaps.length + st.recording;
    if (key !== stripKey || document.querySelector("#strip img.broken")) {
        stripKey = key;
        $("strip-title").textContent = st.lecture ? "Snapshots - " + (st.recording ? "this" : "last") + " lecture (" + st.lecture + "): " + st.snaps.length : "Snapshots";
        $("strip").innerHTML = st.snaps.slice().reverse().map(n =>
            '<a href="/lectures/' + st.lecture + '/snapshots/' + n + '_clean.jpg" target="_blank"><img loading="lazy" src="/lectures/' +
            st.lecture + '/snapshots/' + n + '_clean.jpg" title="' + n + '" onerror="this.className=`broken`"></a>').join("");
    }
}

setInterval(updateStatus, 1000);
setInterval(pollLive, 400);
updateStatus();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # treat "kill" like Ctrl+C
    launch("preview")
    threading.Thread(target=supervise, daemon=True).start()
    try:
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:  # page stopped -> stop the C++ program too (and wait, so the recording is closed cleanly)
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # a second Ctrl+C must not cut this short and
        signal.signal(signal.SIGTERM, signal.SIG_IGN)  # leave ffmpeg holding the camera
        print("Stopping Knightscribe (closing the recording files)...", flush=True)
        with lock:
            stop_program()
        for entry in helpers.values():
            if entry[0] and entry[0].poll() is None:
                os.killpg(entry[0].pid, signal.SIGTERM)
