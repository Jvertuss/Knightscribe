# live_captions.py - the lecture transcript, live, while a lecture is recording (sherpa-onnx streaming).
#
# While recording, knightcribe.cpp makes ffmpeg also send the microphone as raw 16 kHz audio to
# UDP port 5005 on this machine. This program feeds that audio to a small streaming speech model
# (a ~20M-parameter zipformer) that produces words about 1-2 seconds after they are spoken.
# Every finished sentence is added to lectures/<lecture>/transcript.jsonl ({"start", "end", "text"},
# seconds on the recording clock), which cloud.py sends to the website and export.py packages.
# (Whisper no longer runs on the Pi: a more accurate transcript can be made later from recording.mp4.)
#
# It also publishes its state to a small JSON file in RAM (/dev/shm) that web.py serves to the page:
#   {"updated": <unix time>, "state": ..., "t": <seconds into this recording>, "partial": "words so far",
#    "finals": [{"start":..,"end":..,"text":..}, ...], "rtf": <processing time / audio time>}
#
#   <venv>/bin/python live_captions.py     (web.py starts and restarts it for you)
import json, os, re, socket, sys, tarfile, time, urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 5005                      # must match the udp:// output in knightcribe.cpp
RATE = 16000
LIVE = "/dev/shm/knightcribe_live.json" if os.path.isdir("/dev/shm") else os.path.join(HERE, "live.json")
MODEL_NAME = "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/" + MODEL_NAME + ".tar.bz2"
MODEL_DIR = os.path.join(HERE, "models", MODEL_NAME)
KEEP_FINALS = 60                 # how many finished sentences to publish
LECTURES = os.path.join(HERE, "lectures")


def publish(**fields):  # swap the file in whole so the page never reads half of it
    fields["updated"] = time.time()
    with open(LIVE + ".tmp", "w") as f:
        json.dump(fields, f)
    os.replace(LIVE + ".tmp", LIVE)


def ensure_model():  # download + unpack the model the first time (about 130 MB, needs internet)
    if os.path.exists(os.path.join(MODEL_DIR, "tokens.txt")):
        return
    os.makedirs(os.path.dirname(MODEL_DIR), exist_ok=True)
    part = MODEL_DIR + ".tar.bz2.part"
    shown = [0.0]

    def progress(blocks, block_size, total):  # tell the page how far along the download is
        if time.time() - shown[0] > 1 and total > 0:
            shown[0] = time.time()
            publish(state="downloading model %d%% (first start only)" % min(100, blocks * block_size * 100 // total))

    urllib.request.urlretrieve(MODEL_URL, part, progress)
    with tarfile.open(part, "r:bz2") as tar:
        tar.extractall(os.path.dirname(MODEL_DIR), filter="data")
    os.remove(part)


def make_recognizer():
    import sherpa_onnx
    m = MODEL_DIR
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=os.path.join(m, "tokens.txt"),
        encoder=os.path.join(m, "encoder-epoch-99-avg-1.int8.onnx"),  # int8 = smaller and faster on the Pi
        decoder=os.path.join(m, "decoder-epoch-99-avg-1.onnx"),
        joiner=os.path.join(m, "joiner-epoch-99-avg-1.int8.onnx"),
        num_threads=1, sample_rate=RATE, feature_dim=80, decoding_method="greedy_search",
        enable_endpoint_detection=True,       # a pause ends a sentence...
        rule1_min_trailing_silence=2.0,
        rule2_min_trailing_silence=0.8,
        rule3_min_utterance_length=15.0)      # ...and so does talking for 15 s without one


def newest_lecture_folder():  # the recording that just started (knightcribe.cpp names folders by start time)
    try:
        names = [n for n in os.listdir(LECTURES) if re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d", n)]
        return os.path.join(LECTURES, max(names)) if names else None
    except OSError:
        return None


def save(folder, sentence):  # one finished sentence -> the lecture's transcript (one line, written at once)
    if folder:
        try:
            with open(os.path.join(folder, "transcript.jsonl"), "a") as f:
                f.write(json.dumps(sentence) + "\n")
        except OSError:
            pass


def pretty(text):  # the model writes ALL CAPS: make it readable
    text = re.sub(r"\bi\b", "I", text.lower().strip())
    return text[:1].upper() + text[1:]


def result_text(recognizer, stream):  # some sherpa-onnx versions return a string, others an object
    r = recognizer.get_result(stream)
    return (r if isinstance(r, str) else r.text).strip()


def main():
    os.nice(15)  # low priority: the recording always comes first; captions use whatever CPU is left
    recognizer = None
    while recognizer is None:
        try:
            publish(state="downloading model (first start only)")
            ensure_model()
            publish(state="loading model")
            recognizer = make_recognizer()
        except Exception as error:
            publish(state="model setup failed, retrying: " + str(error)[:80])
            time.sleep(30)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)  # room for a burst if we fall behind
    sock.bind(("127.0.0.1", PORT))
    sock.settimeout(0.5)

    stream, samples, finals, utt_start = None, 0, [], None
    folder = None  # the lecture this recording is saved in
    text = ""  # the words of the sentence being spoken right now
    busy = heard = 0.0       # seconds spent decoding / seconds of audio decoded (for the speed readout)
    last_packet = last_publish = 0.0
    last_shown = None
    kept, ended_at = [], 0.0  # sentences of the recording that just ended: still shown for 30 s
    publish(state="idle")
    while True:
        try:
            data = sock.recv(8192)
        except socket.timeout:
            if stream is not None and time.time() - last_packet > 3:  # recording ended
                if text:  # keep the last unfinished sentence
                    sentence = {"start": round(utt_start or 0, 2), "end": round(samples / RATE, 2), "text": pretty(text)}
                    finals.append(sentence)
                    save(folder, sentence)
                kept, ended_at = finals[-KEEP_FINALS:], time.time()
                stream, samples, finals, utt_start, busy, heard, text = None, 0, [], None, 0.0, 0.0, ""
                folder = None
                last_shown = None
            if time.time() - last_publish > 1:
                last_publish = time.time()
                if stream is None:
                    publish(state="idle", t=0, partial="", finals=kept if time.time() - ended_at < 30 else [], rtf=None)
                else:
                    publish(state="listening", t=samples / RATE, partial="", finals=finals[-KEEP_FINALS:],
                            rtf=round(busy / heard, 2) if heard else None)
            continue
        last_packet = time.time()
        if stream is None:  # first audio of a new recording
            stream, samples, finals, utt_start = recognizer.create_stream(), 0, [], None
            folder = newest_lecture_folder()
            # half a second of silence first: this model drops the first words if speech starts instantly
            stream.accept_waveform(RATE, np.zeros(RATE // 2, dtype=np.float32))
        began = time.time()
        audio = np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
        stream.accept_waveform(RATE, audio)
        samples += len(audio)
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        text = result_text(recognizer, stream)
        t = samples / RATE
        if text and utt_start is None:
            utt_start = max(0.0, t - 0.5)  # the sentence began a moment before the first word showed up
        if recognizer.is_endpoint(stream):
            if text:
                sentence = {"start": round(utt_start, 2), "end": round(t, 2), "text": pretty(text)}
                finals.append(sentence)
                save(folder, sentence)
            recognizer.reset(stream)
            text, utt_start = "", None
        busy += time.time() - began
        heard += len(audio) / RATE
        shown = (text, len(finals))
        if shown != last_shown or time.time() - last_publish > 1:  # only write when something changed
            last_shown, last_publish = shown, time.time()
            publish(state="listening", t=round(t, 2), partial=pretty(text) if text else "",
                    partial_start=round(utt_start, 2) if utt_start is not None else None,
                    finals=finals[-KEEP_FINALS:], rtf=round(busy / heard, 2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
