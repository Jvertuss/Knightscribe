# cloud.py - sends the lecture to the Knightscribe website backend while it is happening, then sends the
# finished lecture when it ends. web.py starts it (and restarts it if it stops); what it prints goes to
# cloud.log (watch it with: tail -f cloud.log). Don't also run it by hand: two copies would send everything twice.
#
# While a lecture is recording it, about every 3 seconds:
#   1. creates the lecture on the backend (once; the lecture's id is its folder name, e.g. 2026-10-10_15-32-41)
#   2. marks the stream "live" (once)
#   3. sends every new transcript line from lectures/<lecture>/transcript.jsonl
#   4. sends every new whiteboard / slide snapshot, as soon as its text has been read (snapshots.csv)
# When the recording stops it tells the backend the lecture has ended. A few seconds later (once live_captions.py
# has saved the last sentence) it runs export.py and sends the finished lecture.json to the backend once, which replaces the live copy with the
# clean final one. Then it joins the video pieces and the audio into a compressed lectures/<lecture>/recording.mp4,
# uploads it to the backend's database and gives the lecture that link, so students can rewatch it from anywhere.
# (If the upload fails, the lecture gets the Pi's own link instead, which works on the classroom Wi-Fi.)
# The backend's AI writes the lecture summary (every minute while live, and a final one) and practice questions.
# It writes cloud_status.json (what it is doing) and lectures/<lecture>/cloud_state.json (what it already sent),
# so stopping and restarting it never sends anything twice. No third-party packages are needed.
import csv, glob, json, os, re, subprocess, sys, time, urllib.error, urllib.request, wave

# ====================================== SETTINGS ======================================
BASE_URL = "https://knightscribe-api.onrender.com"   # the backend (no slash at the end); backend.txt overrides it
STREAM_URL = "http://knightcribe.local:5000/video"   # the live video (web.py); students' browsers open this link
RECORDING_BASE = "http://knightcribe.local:5000"     # web.py serves lectures/<lecture>/recording.mp4 from here
USE_WHISPER = True        # when the backend has Whisper, send it the audio pieces for an accurate transcript
UPLOAD_RECORDING = True   # send the finished video to the backend's database (falls back to the Pi link if that fails)
MAX_UPLOAD_MB = 140       # the backend refuses larger files; a 5-minute lecture is about 30 MB after compression
COURSE_ID = ""       # leave empty: the course is picked when a lecture starts (see "Which course" below)
API_KEY = ""         # the backend needs no key right now; fill this in only if that changes
AUTH_HEADER = "Authorization"
AUTH_PREFIX = "Bearer "

# Which course: the course is decided when a lecture starts, in this order:
#   1. the course.txt file next to cloud.py (one line: the course id) - change it any time before Start Recording
#   2. COURSE_ID above, if you filled it in
#   3. the backend's own list of courses: if it has exactly one, that one is used
# With several courses and no course.txt, cloud.py says so and waits for you to create course.txt.

# The backend's endpoints (checked against https://knightscribe-api.onrender.com/openapi.json)
COURSES_PATH = "/courses"
CREATE_LECTURE_PATH = "/lectures"
STREAM_PATH = "/lectures/{lecture_id}/stream"
TRANSCRIPT_PATH = "/lectures/{lecture_id}/transcript"
BOARD_PATH = "/lectures/{lecture_id}/board-events"
END_PATH = "/lectures/{lecture_id}/end"
IMPORT_PATH = "/courses/{course_id}/hardware-import"
LECTURE_PATH = "/lectures/{lecture_id}"
COMPLETE_PATH = "/lectures/{lecture_id}/complete"  # takes final_summary + recording_url
RECORDING_PATH = "/lectures/{lecture_id}/recording"  # PUT the video file; students watch it with GET
SUMMARY_PATH = "/lectures/{lecture_id}/summary/generate"  # the backend's AI writes the summary (?final=true at the end)
QUIZ_PATH = "/lectures/{lecture_id}/quiz/generate"        # the backend's AI writes practice questions
WHISPER_PATH = "/whisper"                                  # does the backend have Whisper?
AUDIO_PATH = "/lectures/{lecture_id}/audio/{index}"        # PUT one 15-second WAV piece (?start=seconds)
AUDIO_PENDING_PATH = "/lectures/{lecture_id}/audio/pending"  # pieces Whisper still has to do
COURSE_ID_KEY = "id"  # the name of the course id in each course the backend lists


def backend_id(lecture):  # the finished lecture (hardware-import) is stored as lecture_<folder>: use that id from the start
    return lecture if lecture.startswith("lecture_") else "lecture_" + lecture


def create_payload(lecture, course):
    return {"id": backend_id(lecture), "course_id": int(course) if str(course).isdigit() else course,
            "title": "Lecture " + lecture}


def transcript_payload(n, seg):  # n = this line's number (0, 1, 2...); sending the same number again just updates it
    return {"chunk_number": n, "start_seconds": seg["start"], "end_seconds": seg["end"], "text": seg["text"]}


def board_payload(lecture, visual):
    # Only the photo (web.py serves it from the Pi) goes to the website. The text Tesseract reads off the board
    # is too unreliable, so it stays on the Pi: the website's search and AI never see it.
    image = "%s/lectures/%s/snapshots/%s" % (RECORDING_BASE.rstrip("/"), lecture, visual["file"])
    return {"timestamp_seconds": visual["time"], "image_url": image, "ocr_text": None,
            "description": None, "event_type": visual["kind"]}


def import_payload(doc):  # doc = the whole export/lecture.json (its lecture_id is the same id used above)
    # No board / slide snapshots here: the import would store them without their photos (and with the unreliable
    # board text). send_final() sends them again afterwards, photos only.
    return {**doc, "visuals": [], "stream_protocol": "mjpeg" if STREAM_URL else None,
            "live_stream_url": STREAM_URL or None}
# ======================================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
LECTURES = os.path.join(HERE, "lectures")

# backend.txt next to cloud.py (one line, e.g. http://192.168.1.25:8000) sends everything to that backend instead,
# for example the laptop running the website with its own local database.
try:
    with open(os.path.join(HERE, "backend.txt")) as _f:
        BASE_URL = _f.read().strip().rstrip("/") or BASE_URL
except OSError:
    pass
STATUS = os.path.join(HERE, "cloud_status.json")
EVERY = 3              # seconds between checks
START_WAIT = 60        # a new lecture that never shows as recording within this many seconds is treated as ended
SUMMARY_EVERY = 60     # seconds between AI summaries during a live lecture (only when new speech came in)
WHISPER_WAIT = 180     # at the end, wait at most this long for Whisper to finish the last pieces
FINISH_WAIT = 10       # after the recording stops, wait this long for the last sentence (the streaming model saves
                       # it within ~3 s), then package and send the finished lecture
NAME = r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d"


def set_status(state, message, lecture=None):
    try:
        with open(STATUS + ".tmp", "w") as f:
            json.dump({"state": state, "message": message, "lecture": lecture, "time": time.time()}, f)
        os.replace(STATUS + ".tmp", STATUS)
    except OSError:
        pass
    print("[cloud] %s: %s" % (state, message), flush=True)


def call(method, path, body=None):  # -> (http status, reply)
    req = urllib.request.Request(BASE_URL.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if API_KEY:
        req.add_header(AUTH_HEADER, AUTH_PREFIX + API_KEY)
    try:
        # 60 s: a free Render server falls asleep and needs up to a minute to wake on the first request
        with urllib.request.urlopen(req, timeout=60) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    try:
        reply = json.loads(raw) if raw else {}
    except ValueError:
        reply = {}
    return code, reply


def must(code, what, reply=None):
    if code not in (200, 201):
        detail = ""
        if isinstance(reply, dict) and reply.get("detail"):
            detail = ": " + str(reply["detail"])[:200]
        raise RuntimeError("%s failed (HTTP %s)%s" % (what, code, detail))


def choose_course():  # the course id for a new lecture
    try:
        with open(os.path.join(HERE, "course.txt")) as f:
            chosen = f.read().strip()
        if chosen:
            return chosen
    except OSError:
        pass
    if COURSE_ID:
        return COURSE_ID
    code, reply = call("GET", COURSES_PATH)
    must(code, "asking the backend for its courses", reply)
    if isinstance(reply, dict):  # {"courses": [...]} or {"items": [...]}
        reply = next((v for v in reply.values() if isinstance(v, list)), [])
    ids = [c.get(COURSE_ID_KEY) if isinstance(c, dict) else c for c in reply]
    ids = [str(i) for i in ids if i is not None]
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise RuntimeError("the backend has no courses yet: create one, or put its id in course.txt")
    raise RuntimeError("several courses exist (%s): put the one you want in course.txt (one line, the id)" % ", ".join(ids))


def state_path(lecture):
    return os.path.join(LECTURES, lecture, "cloud_state.json")


def load_state(lecture):
    try:
        with open(state_path(lecture)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(lecture, st):
    with open(state_path(lecture) + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(state_path(lecture) + ".tmp", state_path(lecture))


def newest_lecture():
    try:
        found = sorted(n for n in os.listdir(LECTURES)
                       if re.fullmatch(NAME, n) and os.path.isdir(os.path.join(LECTURES, n)))
    except OSError:
        return None
    return found[-1] if found else None


def read_json(name):
    try:
        with open(os.path.join(HERE, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def transcript_lines(lecture):  # finished transcript lines, in order
    out = []
    try:
        with open(os.path.join(LECTURES, lecture, "transcript.jsonl")) as f:
            for line in f:
                try:
                    item = json.loads(line)
                    text = re.sub(r"\s+", " ", item.get("text") or "").strip()
                    if text:
                        out.append({"start": float(item["start"]), "end": float(item["end"]), "text": text})
                except (ValueError, KeyError, TypeError):
                    continue  # a half-written last line is picked up on the next check
    except OSError:
        pass
    return out


def visual_events(lecture):
    """Whiteboard / slide snapshots, oldest first: {"time", "kind", "file"}.

    snapshots.csv gets its row once the photo is saved, so every row's photo is ready. (Tesseract's text is not
    waited for: it is not sent to the website.)"""
    out = []
    try:
        with open(os.path.join(LECTURES, lecture, "snapshots.csv"), newline="") as f:
            for row in csv.DictReader(f):
                try:
                    out.append({"time": float(row["seconds"]), "kind": row.get("kind") or "whiteboard",
                                "file": row["file"]})
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return out


def audio_pieces(lecture, finished):  # finished 15-second WAV pieces: [(index, path, start seconds)]
    folder = os.path.join(LECTURES, lecture, "chunks")
    try:
        names = sorted(n for n in os.listdir(folder) if re.fullmatch(r"chunk_\d{5}\.wav", n))
    except OSError:
        return []
    if not (finished or os.path.exists(os.path.join(folder, "DONE"))):
        names = names[:-1]  # the newest piece is still being recorded
    out, start = [], 0.0
    for n in names:
        path = os.path.join(folder, n)
        try:
            with wave.open(path) as w:
                length = w.getnframes() / w.getframerate()
        except (OSError, wave.Error, EOFError):
            break  # a broken or half-written piece: stop here, keep the times right
        out.append((int(n[6:11]), path, round(start, 2)))
        start += length
    return out


def send_audio(lecture, st, finished=False):  # new audio pieces -> the backend's Whisper
    lid = st["lecture_id"]
    for index, path, start in audio_pieces(lecture, finished)[st.get("audio_sent", 0):]:
        with open(path, "rb") as f:
            data = f.read()
        req = urllib.request.Request(BASE_URL.rstrip("/") + AUDIO_PATH.format(lecture_id=lid, index=index)
                                     + "?start=%s" % start, data=data, method="PUT",
                                     headers={"Content-Type": "audio/wav"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError("sending an audio piece to Whisper failed (HTTP %s)" % e.code)
        st["audio_sent"] = st.get("audio_sent", 0) + 1
        save_state(lecture, st)


def whisper_pending(st):  # pieces the backend's Whisper still has to transcribe (0 if unknown)
    code, reply = call("GET", AUDIO_PENDING_PATH.format(lecture_id=st["lecture_id"]))
    return reply.get("pending", 0) if code == 200 else 0


def next_lecture_info():  # the title / course the website chose when it started this recording (web.py writes it)
    info = read_json("next_lecture.json")
    return info if time.time() - info.get("time", 0) < 600 else {}  # older than 10 minutes: not for this lecture


def sync_live(lecture, st):
    if "lecture_id" not in st:
        info = next_lecture_info()
        course = str(info.get("course_id") or "") or choose_course()
        payload = create_payload(lecture, course)
        if info.get("title"):
            payload["title"] = info["title"]
        code, reply = call("POST", CREATE_LECTURE_PATH, payload)
        if code == 409 or (code == 400 and "exist" in str(reply).lower()):
            code = 200  # the backend already has this lecture (cloud_state.json was lost): carry on with it
        must(code, "creating the lecture", reply)
        st["lecture_id"], st["course_id"] = backend_id(lecture), course
        # Whisper on the backend (accurate, ~20 s behind) or the Pi's streaming transcript (instant, rougher)
        code, reply = call("GET", WHISPER_PATH)
        st["whisper"] = bool(USE_WHISPER and code == 200 and reply.get("available"))
        print("[cloud] transcript: %s" % ("Whisper on the backend" if st["whisper"] else "the Pi's streaming model"),
              flush=True)
        save_state(lecture, st)
        try:
            os.remove(os.path.join(HERE, "next_lecture.json"))  # used: the next recording must not reuse it
        except OSError:
            pass
    lid = st["lecture_id"]

    if not st.get("stream_sent"):
        # the backend refuses "live" without the video link
        code, reply = call("PUT", STREAM_PATH.format(lecture_id=lid), {"stream_status": "live", "stream_protocol": "mjpeg",
                                                                       "live_stream_url": STREAM_URL})
        must(code, "marking the stream live", reply)
        st["stream_sent"] = True
        save_state(lecture, st)

    if st.get("whisper"):
        send_audio(lecture, st)
    else:
        lines = transcript_lines(lecture)
        for n in range(st.get("sent", 0), len(lines)):
            code, reply = call("POST", TRANSCRIPT_PATH.format(lecture_id=lid), transcript_payload(n, lines[n]))
            must(code, "sending a transcript line", reply)
            st["sent"] = n + 1
            save_state(lecture, st)

    # the live summary: rewritten by the backend's AI every minute while new speech comes in
    heard = st.get("sent", 0) + st.get("audio_sent", 0)
    if heard > st.get("summary_lines", 0) and time.time() - st.get("summary_time", 0) > SUMMARY_EVERY:
        st["summary_time"] = time.time()  # also after a failure: try again in a minute, not every 3 s
        code, reply = call("POST", SUMMARY_PATH.format(lecture_id=lid))
        if code == 200:
            st["summary_lines"] = heard
        elif code != 400:  # 400 = no transcript yet (Whisper still working); the AI is optional anyway
            print("[cloud] live summary skipped (HTTP %s): %s" % (code, str(reply.get("detail", ""))[:120]), flush=True)
        save_state(lecture, st)

    visuals = visual_events(lecture)
    for n in range(st.get("visual_sent", 0), len(visuals)):
        code, reply = call("POST", BOARD_PATH.format(lecture_id=lid), board_payload(lecture, visuals[n]))
        must(code, "sending a board / slide event", reply)
        st["visual_sent"] = n + 1
        save_state(lecture, st)


def send_end(lecture, st):  # the recording has stopped: tell the backend (once)
    if not st.get("ended"):
        code, reply = call("POST", END_PATH.format(lecture_id=st["lecture_id"]))
        must(code, "marking the lecture ended", reply)
        code, reply = call("PUT", STREAM_PATH.format(lecture_id=st["lecture_id"]), {"stream_status": "ended"})
        must(code, "marking the stream ended", reply)
        st["ended"] = True
        save_state(lecture, st)


def send_final(lecture, st):
    # The website already has everything (sent live). The hardware-import is no longer used: it would replace the
    # transcript (Whisper's) with the Pi's streaming one and drop the board photos. export.py still packages the
    # lecture on the Pi (export/), for LLMs or a database. send_recording() marks the lecture complete.
    try:
        import export  # export.py, in this same folder
        export.export(lecture)
    except Exception as e:  # only local files: never hold up the lecture for it
        print("[cloud] export.py failed: %s" % e, flush=True)
    st["imported"] = True
    save_state(lecture, st)


# Compressed for the web: 480p at 15 pictures a second is plenty for a lecture and about 10x smaller than the
# recording (a 5-minute lecture is about 30 MB). The Pi's hardware encoder is tried first; libx264 is the fallback.
ENCODERS = [["-c:v", "h264_v4l2m2m", "-b:v", "900k"],
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30"]]


def make_recording(lecture):  # -> path of recording.mp4, or None if there is no video
    """Joins the 5-minute video pieces and the separate audio into one compressed recording.mp4."""
    folder = os.path.join(LECTURES, lecture)
    out = os.path.join(folder, "recording.mp4")
    if os.path.exists(out):
        return out
    parts = sorted(glob.glob(os.path.join(folder, "video_*.mkv")))
    if not parts:
        print("[cloud] no video pieces in %s, so no recording" % lecture, flush=True)
        return None
    with open(os.path.join(folder, "recording_parts.txt"), "w") as f:
        f.writelines("file '%s'\n" % os.path.basename(p) for p in parts)
    has_audio = os.path.exists(os.path.join(folder, "audio.flac"))
    tmp = os.path.join(folder, "recording.tmp")
    for encoder in ENCODERS:
        cmd = ["nice", "-n", "10", "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", "recording_parts.txt"]
        if has_audio:
            cmd += ["-i", "audio.flac", "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "64k", "-ac", "1"]
        else:
            cmd += ["-map", "0:v"]
        # +faststart puts the index at the front, so the browser can start playing and skip around at once
        cmd += ["-vf", "fps=15,scale=-2:480", "-pix_fmt", "yuv420p"] + encoder + \
               ["-movflags", "+faststart", "-f", "mp4", "recording.tmp"]
        print("[cloud] compressing the recording with %s..." % encoder[1], flush=True)
        try:
            result = subprocess.run(cmd, cwd=folder, capture_output=True, text=True, timeout=1800)
            error = result.stderr.strip()[-300:]
            ok = result.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0
        except (OSError, subprocess.TimeoutExpired) as e:
            error, ok = str(e), False
        if ok:
            os.replace(tmp, out)
            return out
        print("[cloud] %s could not make recording.mp4: %s" % (encoder[1], error), flush=True)
    return None


def upload_recording(lid, path):  # the video file -> the backend's database (raises on failure)
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(BASE_URL.rstrip("/") + RECORDING_PATH.format(lecture_id=lid), data=data,
                                 method="PUT", headers={"Content-Type": "video/mp4"})
    if API_KEY:
        req.add_header(AUTH_HEADER, AUTH_PREFIX + API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:  # a slow upload link may need a few minutes
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s %s" % (e.code, e.read()[:200]))


def send_recording(lecture, st):  # tell the backend where students can rewatch the lecture (once) -> the link or None
    path = make_recording(lecture)
    url = None
    if path:
        url = "%s/lectures/%s/recording.mp4" % (RECORDING_BASE.rstrip("/"), lecture)  # the Pi's copy
        size_mb = os.path.getsize(path) / 1e6
        if UPLOAD_RECORDING and size_mb <= MAX_UPLOAD_MB:
            print("[cloud] uploading the recording (%.0f MB)..." % size_mb, flush=True)
            try:
                upload_recording(backend_id(lecture), path)
                url = BASE_URL.rstrip("/") + RECORDING_PATH.format(lecture_id=backend_id(lecture))
                print("[cloud] recording saved in the database", flush=True)
            except Exception as e:  # old backend, no internet...: students use the Pi's copy instead
                print("[cloud] upload failed, using the Pi's copy instead: %s" % e, flush=True)
        elif UPLOAD_RECORDING:
            print("[cloud] recording is %.0f MB (limit %d): using the Pi's copy" % (size_mb, MAX_UPLOAD_MB), flush=True)
    # marks the lecture "completed" (with its recording link, or none). The live copy and the imported copy
    # can have different ids in older lectures: do both.
    for lid in sorted({backend_id(lecture), st["lecture_id"]}):
        code, current = call("GET", LECTURE_PATH.format(lecture_id=lid))
        if code == 404:
            continue
        must(code, "reading the lecture", current)
        # /complete replaces the summary too: send back the one the lecture already has
        summary = current.get("final_summary") or current.get("live_summary") or ""
        code, reply = call("PUT", COMPLETE_PATH.format(lecture_id=lid), {"final_summary": summary, "recording_url": url})
        must(code, "marking the lecture complete", reply)
    # also when there is no video: a lecture without one must not be retried forever
    st["recording_done"], st["recording_url"] = True, url
    save_state(lecture, st)
    return url


def finish_ai(lecture, st):  # the final summary and practice questions, written by the backend's AI (once)
    lid = backend_id(lecture)
    for what, path in (("final summary", SUMMARY_PATH.format(lecture_id=lid) + "?final=true"),
                       ("practice questions", QUIZ_PATH.format(lecture_id=lid) + "?count=4")):
        code, reply = call("POST", path)
        if code == 200:
            print("[cloud] AI %s done" % what, flush=True)
        else:  # e.g. no speech in the lecture: the teacher can still press the AI buttons on the website
            print("[cloud] AI %s skipped (HTTP %s): %s" % (what, code, str(reply.get("detail", ""))[:120]), flush=True)
    st["ai_done"] = True  # once only, also after a failure
    save_state(lecture, st)


def done_message(url):
    return "the finished lecture is on the website" + (", with its recording" if url else " (no recording, see above)")


def main():
    print("cloud.py running: sending to %s (Ctrl+C stops it)" % BASE_URL, flush=True)
    idle_since = None
    while True:
        lecture = newest_lecture()
        try:
            if lecture:
                st = load_state(lecture)
                recording = bool(read_json("status.json").get("recording"))
                if recording:
                    idle_since = None
                elif idle_since is None:
                    idle_since = time.time()
                if st.get("imported") and st.get("recording_done") and st.get("ai_done"):
                    set_status("done", done_message(st.get("recording_url")), lecture)
                elif st.get("imported"):  # the lecture is in; its video link or AI notes are not yet
                    if not st.get("recording_done"):
                        send_recording(lecture, st)
                    if not st.get("ai_done"):
                        finish_ai(lecture, st)
                    set_status("done", done_message(st.get("recording_url")), lecture)
                else:
                    sync_live(lecture, st)
                    if "first_seen" not in st:
                        st["first_seen"] = time.time()
                        save_state(lecture, st)
                    if recording:
                        if not st.get("seen_recording"):
                            st["seen_recording"] = True
                            save_state(lecture, st)
                        set_status("live", "live on the website: %d transcript lines, %d board / slide events sent"
                                   % (st.get("sent", 0), st.get("visual_sent", 0)), lecture)
                    elif not st.get("seen_recording") and time.time() - st["first_seen"] < START_WAIT:
                        # the new lecture folder appears a moment before status.json says "recording":
                        # don't end the lecture during that gap
                        set_status("starting", "new lecture found, waiting for the recording to start", lecture)
                    else:
                        send_end(lecture, st)
                        if st.get("whisper") and time.time() - idle_since > FINISH_WAIT:
                            send_audio(lecture, st, finished=True)  # the last pieces, once the recording is closed
                            left = whisper_pending(st)
                            if left and time.time() - idle_since < WHISPER_WAIT:
                                set_status("finishing", "Whisper is transcribing the last %d audio pieces" % left, lecture)
                                time.sleep(EVERY)
                                continue
                        if time.time() - idle_since > FINISH_WAIT:
                            send_final(lecture, st)
                            url = send_recording(lecture, st)
                            finish_ai(lecture, st)
                            set_status("done", done_message(url), lecture)
                        else:
                            set_status("finishing", "recording ended: saving the last sentence", lecture)
            else:
                set_status("waiting", "no lecture yet", None)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # no internet / backend down: keep the files, try again in a few seconds
            set_status("retrying", "%s (will try again)" % e, lecture)
        time.sleep(EVERY)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ncloud.py stopped.")
