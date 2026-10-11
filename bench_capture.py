# bench_capture.py - finds out which part of the capture pipeline uses the CPU.
# It runs the same ffmpeg work as knightcribe.cpp in four combinations for 10 seconds each and prints
# how many frames were recorded and how much CPU each one needed.
#
# Stop Knightscribe first (Ctrl+C in the send_code window) so the camera is free, then:
#   python3 ~/knightcribe/Knightcribe-Starter/bench_capture.py
import os, re, resource, subprocess, sys, tempfile

SECONDS = 10
def cam(decoder=None):  # decoder: e.g. "mjpeg_v4l2m2m" = ask the Pi's video chip to decode the JPEGs
    return (["ffmpeg", "-nostdin", "-y", "-hide_banner", "-stats", "-loglevel", "error", "-t", str(SECONDS),
             "-f", "v4l2", "-input_format", "mjpeg", "-video_size", "1920x1080", "-framerate", "30",
             "-thread_queue_size", "512"] + (["-c:v", decoder] if decoder else []) + ["-i", "/dev/video0"])


def parts(tmp):
    return {
        "decode": ["-map", "0:v", "-f", "null", "-"],
        "convert": ["-map", "0:v", "-vf", "format=yuv420p", "-f", "null", "-"],
        "fastconvert": ["-map", "0:v", "-vf", "scale=flags=fast_bilinear,format=yuv420p", "-c:v", "h264_v4l2m2m",
                        "-b:v", "8M", "-g", "60", "-f", "matroska", os.path.join(tmp, "fast.mkv")],
        "nv12": ["-map", "0:v", "-vf", "scale=flags=fast_bilinear,format=nv12", "-c:v", "h264_v4l2m2m",
                 "-b:v", "8M", "-g", "60", "-f", "matroska", os.path.join(tmp, "nv12.mkv")],
        "record": ["-map", "0:v", "-c:v", "h264_v4l2m2m", "-pix_fmt", "yuv420p", "-b:v", "8M", "-g", "60",
                   "-f", "matroska", os.path.join(tmp, "rec.mkv")],
        "preview": ["-map", "0:v", "-vf", "fps=12,scale=960:540", "-q:v", "7", "-f", "image2", "-update", "1",
                    os.path.join(tmp, "live.jpg")],
        "detector": ["-map", "0:v", "-vf", "fps=2", "-pix_fmt", "bgr24", "-f", "rawvideo", "/dev/null"],
    }


def run(label, names, tmp, decoder=None):
    p = parts(tmp)
    cmd = cam(decoder) + [a for n in names for a in p[n]]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    done = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    frames = re.findall(r"frame=\s*(\d+)", done.stderr.replace("\r", "\n"))
    last = int(frames[-1]) if frames else 0  # the LAST progress line has the total
    print("%-38s frames: %-4s (%4.1f fps)  CPU: %4.0f%% of one core  %s" % (
        label, last or "?", last / SECONDS, cpu / SECONDS * 100,
        "" if done.returncode == 0 else "(ffmpeg error: " + done.stderr.strip().splitlines()[-1][:80] + ")"))


if not os.path.exists("/dev/video0"):
    sys.exit("no camera at /dev/video0")
if subprocess.run(["fuser", "/dev/video0"], capture_output=True).stdout.strip():
    sys.exit("The camera is in use. Stop Knightscribe first (Ctrl+C in the send_code window).")
with tempfile.TemporaryDirectory() as tmp:
    print("Each test runs %d seconds. 300 frames = a full 30 fps.\n" % SECONDS)
    run("1  recording, normal conversion", ["record"], tmp)
    run("2  recording, fast_bilinear convert", ["fastconvert"], tmp)
    run("3  recording, fast convert to nv12", ["nv12"], tmp)
    run("4  everything (like the app)", ["record", "preview", "detector"], tmp)
