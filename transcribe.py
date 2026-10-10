# transcribe.py - live lecture transcription on the Pi (faster-whisper, CPU, int8).
#
# While a lecture is recording, knightcribe.cpp makes ffmpeg cut the microphone into short 16 kHz mono
# files:  lectures/<lecture>/chunks/chunk_00000.wav, chunk_00001.wav ...  (CHUNK_SECONDS each).
# This program (started and watched by web.py) picks them up as they finish, transcribes them, and
# appends the text to  lectures/<lecture>/transcript.jsonl  and  transcript.txt  with times in
# seconds on the SAME clock as the video and the board snapshots.
#
# Only the lecture being recorded (or the one that just ended) is handled here; older lectures are skipped.
# It runs with 2 threads at slightly lowered priority so it never starves the recorder. If it falls behind real
# time it switches from the "base.en" model to the faster "tiny.en" model by itself.
#
#   <venv>/bin/python transcribe.py            run the live worker (web.py does this for you)
#   <venv>/bin/python transcribe.py --bench f  time both models on an audio file f (e.g. a chunk)
import json, os, re, sys, time, wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LECTURES = os.path.join(HERE, "lectures")
STATUS = os.path.join(HERE, "transcribe_status.json")
MODELS = ["base.en", "tiny.en"]  # best accuracy first; falls back to the next one if too slow
THREADS = 2                      # Pi 4 has 4 cores; leave the rest to ffmpeg and the detector
TOO_SLOW = 0.9                   # processing time / audio time above this = falling behind
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "okay"}
MAX_BACKLOG = 4                  # chunks waiting before we give up on the bigger model

status = {"state": "starting", "model": MODELS[0], "rtf": None, "backlog": 0, "chunks_done": 0,
          "lecture": None, "covered_until": 0}  # covered_until: seconds of this lecture already in the transcript


def write_status(**changes):  # page reads this file; swap it in whole so it never sees half of it
    status.update(changes)
    with open(STATUS + ".tmp", "w") as f:
        json.dump(status, f)
    os.replace(STATUS + ".tmp", STATUS)


def duration(path):  # length of a finished wav chunk in seconds
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def read_wav(path):  # our chunks are 16 kHz mono 16-bit, so read them directly (no ffmpeg/PyAV needed)
    with wave.open(path) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("chunk is not 16 kHz mono 16-bit: " + path)
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def load_model(name):
    from faster_whisper import WhisperModel  # imported late so --help style errors stay readable
    write_status(state="loading " + name, model=name)
    return WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=THREADS)


def transcribe(model, wav, previous_text):
    segments, _ = model.transcribe(
        read_wav(wav), language="en", beam_size=1, vad_filter=True,   # greedy + skip silence = much faster
        condition_on_previous_text=False,                   # avoids the model repeating itself
        initial_prompt=previous_text[-150:] or None)        # last words give the next chunk context
    out = []
    for s in segments:
        text = s.text.strip()
        if not text or s.no_speech_prob >= 0.8:             # drop noise the model "heard" as text
            continue
        # Whisper invents stock phrases like "Thank you." over silence: drop them when it is unsure
        if text.lower().strip(" .!,") in HALLUCINATIONS and (s.no_speech_prob > 0.3 or s.avg_logprob < -0.6):
            continue
        out.append((s.start, s.end, text))
    return out


def bench(path):
    from faster_whisper import WhisperModel
    seconds = duration(path) if path.endswith(".wav") else 0
    for name in MODELS:
        model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=THREADS)
        t = time.time()
        text = " ".join(x[2] for x in transcribe(model, path, ""))
        took = time.time() - t
        rtf = f"{took / seconds:.2f}x real time" if seconds else f"{took:.1f} s"
        print(f"{name}: {rtf}  ({took:.1f} s)  ->  {text[:100]}")


def pending_chunks(lecture):  # finished chunks not yet in the transcript, oldest first
    folder = os.path.join(LECTURES, lecture, "chunks")
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".wav"))
    except OSError:
        return [], True  # no audio chunks for this lecture: nothing to do
    finished = os.path.exists(os.path.join(folder, "DONE"))  # recorder has stopped
    if not finished:  # recorder was killed without writing DONE: no new audio for 90 s
        newest = os.path.join(folder, names[-1]) if names else folder
        finished = time.time() - os.path.getmtime(newest) > 90
    if not finished:
        names = names[:-1]  # the newest chunk is still being written
    marker = os.path.join(LECTURES, lecture, "transcript.progress")
    try:
        done = int(open(marker).read())
    except (OSError, ValueError):
        done = 0
    return [(i, os.path.join(folder, n)) for i, n in enumerate(names) if i >= done], finished


def work_on(lecture, model_state):  # transcribe ONE waiting chunk of this lecture
    todo, finished = pending_chunks(lecture)
    status["backlog"] = len(todo)
    if status["lecture"] != lecture:
        status["lecture"], status["covered_until"] = lecture, 0
        model_state["previous"] = ""
        if not finished and model_state["name"] != MODELS[0]:  # a new live lecture: try the better model again
            model_state["name"] = MODELS[0]
            model_state["model"] = load_model(MODELS[0])
            model_state["slow"] = 0
    for k, (index, wav) in enumerate(todo[:1]):
        status["backlog"] = len(todo) - k
        folder = os.path.dirname(wav)
        start = sum(duration(os.path.join(folder, f"chunk_{j:05d}.wav")) for j in range(index))
        length = duration(wav)
        t = time.time()
        try:
            found = transcribe(model_state["model"], wav, model_state["previous"])
        except Exception as error:  # a bad chunk must not stop the whole lecture: note it and move on
            print("transcribe error on", wav, "-", error, file=sys.stderr, flush=True)
            found = []
            status["errors"] = status.get("errors", 0) + 1
            status["last_error"] = str(error)[:120]
        took = time.time() - t
        base = os.path.join(LECTURES, lecture)
        with open(os.path.join(base, "transcript.jsonl"), "a") as j, open(os.path.join(base, "transcript.txt"), "a") as txt:
            for a, b, text in found:
                j.write(json.dumps({"start": round(start + a, 2), "end": round(start + b, 2), "text": text}) + "\n")
                txt.write(f"[{int((start + a) // 60)}:{int((start + a) % 60):02d}] {text}\n")
                model_state["previous"] += " " + text
        model_state["previous"] = model_state["previous"][-300:]
        with open(os.path.join(base, "transcript.progress"), "w") as f:  # survive a restart
            f.write(str(index + 1))
        rtf = took / max(length, 0.1)
        model_state["slow"] = model_state["slow"] + 1 if rtf > TOO_SLOW else 0
        status["chunks_done"] += 1
        write_status(state="working", rtf=round(rtf, 2), backlog=len(todo) - k - 1,
                     covered_until=round(start + length, 2))
        # falling behind? use the smaller model for the rest of the lecture
        behind = model_state["slow"] >= 2 or (not finished and len(todo) - k > MAX_BACKLOG)  # old leftovers may queue up
        if behind and model_state["name"] != MODELS[-1]:
            model_state["name"] = MODELS[MODELS.index(model_state["name"]) + 1]
            model_state["model"] = load_model(model_state["name"])
            model_state["slow"] = 0


def main():
    os.nice(15)  # low priority: the recording always comes first; Whisper uses whatever CPU is left
    model_state = {"name": MODELS[0], "model": None, "previous": "", "slow": 0}
    finished_lectures = set()
    # Load the model now, while nothing is recording. The very first start downloads both models
    # (needs internet); the page shows "downloading" until that is done. Retries if the network drops.
    fallback_ready = False
    while model_state["model"] is None or not fallback_ready:
        try:
            write_status(state="downloading/loading models (first start only)", model=MODELS[0])
            if model_state["model"] is None:
                model_state["model"] = load_model(MODELS[0])
            from faster_whisper.utils import download_model
            for name in MODELS[1:]:
                download_model(name)  # fetch the fallback model now so a lecture never waits for it
            fallback_ready = True
        except Exception as error:
            write_status(state="model download failed, retrying: " + str(error)[:80])
            time.sleep(30)
    write_status(state="idle")
    while True:
        # Only the newest lecture is ever transcribed here. Earlier lectures are left alone on purpose:
        # they are meant for the cloud transcription, so the Pi's whole CPU budget goes to the current one.
        try:  # lecture folders are named after their start time, so the newest sorts last
            names = [n for n in os.listdir(LECTURES) if re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d", n)]
            newest = max(names) if names else None
        except OSError:
            newest = None
        busy = False
        if newest:  # show how many audio pieces the recorder has produced (helps spot a recorder problem)
            try:
                status["on_disk"] = sum(n.endswith(".wav") for n in os.listdir(os.path.join(LECTURES, newest, "chunks")))
            except OSError:
                status["on_disk"] = 0
        if newest and newest not in finished_lectures:
            todo, finished = pending_chunks(newest)
            if todo:
                busy = True
                work_on(newest, model_state)  # one chunk, then look again (a newer lecture may have started)
            elif finished:
                finished_lectures.add(newest)
        if not busy:
            write_status(state="idle", backlog=0)
            time.sleep(1)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--bench":
        bench(sys.argv[2])
    else:
        try:
            main()
        except KeyboardInterrupt:
            pass
