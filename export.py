# export.py - packages one finished lecture into files that are ready to send to an LLM or a database.
#
#   python3 export.py [lecture_folder_name]      (no name = the newest lecture)
#
# It reads what the Pi recorded:
#   lectures/<lecture>/transcript.jsonl   what was said:        {"start", "end", "text"}   (transcribe.py)
#   lectures/<lecture>/snapshots.csv      board / slide photos:  seconds,file,kind          (knightcribe.cpp)
#   lectures/<lecture>/snapshots/*.txt    the text read off every board / slide photo
# and writes lectures/<lecture>/export/ :
#   lecture.json    everything in one document (transcript, visuals, and one merged timeline)
#   chunks.jsonl    one JSON object per line: ~45 s of speech + the board / slide text on screen at that time.
#                   Each line has "embedding_text", ready to embed and insert into a vector database.
#   for_llm.txt     the whole lecture as plain text with timestamps, ready to paste into a prompt
# Times are in seconds from the start of the recording (the same clock as the video).
# No third-party packages are needed, so it also runs outside the virtual environment.
import csv, json, os, re, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LECTURES = os.path.join(HERE, "lectures")
CHUNK_SECONDS = 45   # a chunk closes once it covers this much speech...
CHUNK_CHARS = 900    # ...or this many characters
SCHEMA = "knightscribe.lecture.v1"


def lectures():  # lecture folders are named after their start time: 2026-10-10_15-32-41
    try:
        return sorted(n for n in os.listdir(LECTURES) if re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d", n)
                      and os.path.isdir(os.path.join(LECTURES, n)))
    except OSError:
        return []


def squash(text):  # one tidy line: no stray line breaks or double spaces
    return re.sub(r"\s+", " ", text or "").strip()


def clock(seconds):
    seconds = int(seconds)
    return "%d:%02d:%02d" % (seconds // 3600, seconds % 3600 // 60, seconds % 60)


def read_transcript(folder):
    out = []
    try:
        with open(os.path.join(folder, "transcript.jsonl")) as f:
            for line in f:
                try:
                    item = json.loads(line)
                    text = squash(item.get("text"))
                    if text:
                        out.append({"start": float(item["start"]), "end": float(item["end"]), "text": text})
                except (ValueError, KeyError, TypeError):
                    continue  # a half-written last line must not break the export
    except OSError:
        pass
    return sorted(out, key=lambda s: s["start"])


def read_visuals(folder):
    out = []
    try:
        with open(os.path.join(folder, "snapshots.csv")) as f:
            for row in csv.DictReader(f):
                try:
                    name = row["file"]
                    stem = os.path.join(folder, "snapshots", os.path.splitext(name)[0])
                    try:
                        text = open(stem + ".txt").read()
                    except OSError:
                        text = ""
                    lines = [squash(x) for x in text.splitlines() if squash(x)]
                    out.append({"time": float(row["seconds"]), "kind": row.get("kind") or "whiteboard",
                                "file": "snapshots/" + name,
                                "clean_file": "snapshots/" + os.path.splitext(name)[0] + "_clean.jpg",
                                "title": lines[0] if lines else "", "text": "\n".join(lines)})
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return sorted(out, key=lambda v: v["time"])


def started_at(lecture):  # the folder is named after the start time: 2026-10-10_15-32-41
    try:
        return datetime.strptime(lecture, "%Y-%m-%d_%H-%M-%S").isoformat()
    except ValueError:
        return None


def build_chunks(lecture, speech, visuals):
    chunks, current = [], []

    def close():
        if not current:
            return
        start, end = current[0]["start"], current[-1]["end"]
        showing = [v for v in visuals if v["time"] <= start][-1:]      # the picture already up when this began
        during = [v for v in visuals if start < v["time"] <= end]     # pictures that appeared while speaking
        shown = showing + during
        speech_text = " ".join(s["text"] for s in current)
        screen_text = "\n\n".join("[%s] %s" % (v["kind"], v["text"]) for v in shown if v["text"])
        chunks.append({
            "id": "%s:%04d" % (lecture, len(chunks)), "lecture_id": lecture, "start": round(start, 2),
            "end": round(end, 2), "text": speech_text,
            "visual_text": screen_text,
            "visuals": [{"time": v["time"], "kind": v["kind"], "file": v["file"]} for v in shown],
            "embedding_text": speech_text + ("\n\nOn the board / slide:\n" + screen_text if screen_text else ""),
        })
        current.clear()

    for seg in speech:
        current.append(seg)
        if seg["end"] - current[0]["start"] >= CHUNK_SECONDS or sum(len(s["text"]) for s in current) >= CHUNK_CHARS:
            close()
    close()
    if not speech:  # a lecture with pictures but no speech still gets searchable chunks
        for v in visuals:
            chunks.append({"id": "%s:%04d" % (lecture, len(chunks)), "lecture_id": lecture, "start": v["time"],
                           "end": v["time"], "text": "", "visual_text": "[%s] %s" % (v["kind"], v["text"]),
                           "visuals": [{"time": v["time"], "kind": v["kind"], "file": v["file"]}],
                           "embedding_text": "On the board / slide:\n[%s] %s" % (v["kind"], v["text"])})
    return chunks


def export(lecture):
    folder = os.path.join(LECTURES, lecture)
    speech, visuals = read_transcript(folder), read_visuals(folder)
    timeline = sorted(
        [{"time": s["start"], "type": "speech", "text": s["text"]} for s in speech] +
        [{"time": v["time"], "type": v["kind"], "text": v["text"], "file": v["file"]} for v in visuals],
        key=lambda e: (e["time"], e["type"] != "speech"))
    duration = max([s["end"] for s in speech] + [v["time"] for v in visuals] + [0])
    chunks = build_chunks(lecture, speech, visuals)
    doc = {"schema": SCHEMA, "lecture_id": lecture, "started_at": started_at(lecture),
           "duration_seconds": round(duration, 1), "counts": {"speech": len(speech), "slides": sum(v["kind"] == "slide" for v in visuals),
                                                              "whiteboards": sum(v["kind"] == "whiteboard" for v in visuals), "chunks": len(chunks)},
           "transcript": speech, "visuals": visuals, "timeline": timeline}

    out = os.path.join(folder, "export")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "lecture.json"), "w") as f:
        json.dump(doc, f, indent=1)
    with open(os.path.join(out, "chunks.jsonl"), "w") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    with open(os.path.join(out, "for_llm.txt"), "w") as f:
        f.write("Lecture %s (%s long)\n\n" % (lecture, clock(duration)))
        for e in timeline:
            if e["type"] == "speech":
                f.write("[%s] %s\n" % (clock(e["time"]), e["text"]))
            else:
                label = "SLIDE" if e["type"] == "slide" else "WHITEBOARD"
                f.write("\n[%s] %s shown:\n%s\n\n" % (clock(e["time"]), label, e["text"] or "(no readable text)"))
    return out, doc["counts"]


if __name__ == "__main__":
    found = lectures()
    name = sys.argv[1] if len(sys.argv) > 1 else (found[-1] if found else None)
    if not name:
        sys.exit("no lectures found in " + LECTURES)
    if name not in found:
        sys.exit("no lecture called %r in %s" % (name, LECTURES))
    folder, counts = export(name)
    print("Exported %s -> %s  %s" % (name, folder, counts))
