// knightcribe.cpp - Knightscribe capture program
//
//   ./build/knightcribe preview   -> live video + detector running, NOTHING is saved
//   ./build/knightcribe record    -> records lecture video + audio + saves board snapshots
//
// One ffmpeg process owns the camera and the mic. From the camera it makes:
//   1. the recording: 720p30 hardware H.264 in 5-minute pieces (+ FLAC audio, same clock)
//   2. the live video for the page: the camera's own JPEG pictures, copied 30 times a second
//   3. 2 frames per second of raw pixels piped into this program (the detector)
// The microphone is also cut into short 16 kHz chunks (chunks/chunk_00000.wav ...) that
// transcribe.py turns into text while the lecture is still going, and the same audio is sent
// live to UDP port 5005 for live_captions.py (instant draft captions).
// The detector cuts out the teaching area, straightens it, waits until the board has been
// still for 2 s, checks there is writing on it, checks no person is in the way (NanoDet
// neural network), then saves the snapshot + a cleaned, saturated copy + its text (OCR).
// The teaching area can also be a PowerPoint / projector screen (chosen on the page, or detected): then
// a snapshot is saved whenever the slide changes, and the slide's text is read the same way.
// Stop with Ctrl+C (ffmpeg finishes its files cleanly first).

#include <opencv2/opencv.hpp>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#include <cerrno>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

using namespace cv;
namespace fsys = std::filesystem;

// the page's live picture: written to RAM (/dev/shm) so the SD card isn't written 30 times a second
const std::string LIVE_JPG = fsys::is_directory("/dev/shm") ? "/dev/shm/knightscribe_live.jpg" : "live.jpg";

// ---------- settings you might tune ----------
const int W = 1280, H = 720;      // camera resolution (also sent to ffmpeg). 720p30 keeps the Pi 4 smooth and cool
                                  // while it also transcribes; use 1920, 1080 for a sharper board if it keeps up
const int VISION_FPS = 2;         // frames per second the detector looks at while recording
const int PREVIEW_FPS = 1;        // ...and while only previewing (nothing is saved, so a slower look is plenty)
const int CHUNK_SECONDS = 15;     // length of each audio piece handed to live transcription
const int MOTION_DIFF = 25;       // color change that counts as "moving" (people, arms)
const int INK_DIFF = 18;          // color change that counts as writing (low = faint marker counts)
const double STILL = 0.003;       // board is "still" if under 0.3% of it moved
const int STILL_SECONDS = 2;      // the board must stay still this long before the heavier checks run
const double SLIDE_CHANGE = 0.02;  // slides/projector: a new picture once over 2% of the screen differs
const double NEW_CONTENT = 0.0015; // snapshot only if over 0.15% differs from the last one
const double MIN_INK = 0.002;     // board check: at least 0.2% of the board must be writing
const float PERSON_SCORE = 0.45f; // NanoDet confidence needed to call something a person

struct Config {                   // lives in config.json (the web page edits it)
    std::vector<Point2f> corners; // TL,TR,BR,BL as fractions of the picture; empty = no area
    int exposure = 0;             // 0 = auto, otherwise manual (units of 0.1 ms)
    std::string mic = "plughw:CARD=Microphone";  // "" = record without audio
    std::string surface = "auto";  // "whiteboard", "slides" (PowerPoint / projector) or "auto" (decide from the picture)
};

// Put 4 clicked points in TL,TR,BR,BL order no matter which order they were clicked in.
std::vector<Point2f> orderCorners(std::vector<Point2f> p) {
    auto pick = [&](auto score) {
        return *std::min_element(p.begin(), p.end(), [&](Point2f a, Point2f b) { return score(a) < score(b); });
    };
    return {pick([](Point2f q) { return q.x + q.y; }), pick([](Point2f q) { return q.y - q.x; }),
            pick([](Point2f q) { return -q.x - q.y; }), pick([](Point2f q) { return q.x - q.y; })};
}

// "Auto-find board" (the teacher pressed the button on the page): look for the biggest bright, low-colour,
// four-sided shape in the picture. Returns its corners as fractions of the picture (TL,TR,BR,BL), or nothing.
std::vector<Point2f> findBoard(const Mat& frame) {
    Mat small, gray, hsv, edges;
    double scale = 640.0 / frame.cols;
    resize(frame, small, Size(), scale, scale, INTER_AREA);
    cvtColor(small, gray, COLOR_BGR2GRAY);
    cvtColor(small, hsv, COLOR_BGR2HSV);
    GaussianBlur(gray, gray, Size(5, 5), 0);
    Canny(gray, edges, 40, 120);
    dilate(edges, edges, getStructuringElement(MORPH_RECT, Size(3, 3)));
    double total = (double)small.rows * small.cols, bestScore = 0;
    std::vector<Point2f> best;

    // how "board-like" a shape is: big, bright and nearly colourless inside
    auto score = [&](const std::vector<Point>& poly) {
        Mat mask = Mat::zeros(small.size(), CV_8U);
        fillConvexPoly(mask, poly, Scalar(255));
        Scalar m = mean(hsv, mask);  // m[1] = colour strength, m[2] = brightness
        double whiteness = (m[2] / 255.0) * (1.0 - m[1] / 255.0);
        return contourArea(poly) / total * whiteness * whiteness;
    };
    auto consider = [&](const std::vector<Point>& poly) {
        double a = contourArea(poly) / total;
        if (a < 0.08 || a > 0.95) return;
        double sc = score(poly);
        if (sc > bestScore) {
            bestScore = sc;
            best.clear();
            for (auto& p : poly) best.push_back(Point2f(p.x / (float)small.cols, p.y / (float)small.rows));
        }
    };

    std::vector<std::vector<Point>> contours;
    findContours(edges, contours, RETR_LIST, CHAIN_APPROX_SIMPLE);  // 1) outlines drawn by edges
    for (auto& c : contours) {
        if (contourArea(c) < 0.08 * total) continue;
        std::vector<Point> poly;
        approxPolyDP(c, poly, 0.02 * arcLength(c, true), true);
        if (poly.size() == 4 && isContourConvex(poly)) consider(poly);
    }
    if (best.empty()) {  // 2) fallback: the biggest bright, colourless blob, squared up
        Mat blob;
        inRange(hsv, Scalar(0, 0, 150), Scalar(180, 70, 255), blob);
        morphologyEx(blob, blob, MORPH_CLOSE, getStructuringElement(MORPH_RECT, Size(15, 15)));
        contours.clear();
        findContours(blob, contours, RETR_EXTERNAL, CHAIN_APPROX_SIMPLE);
        double biggest = 0;
        std::vector<Point> hull;
        for (auto& c : contours)
            if (contourArea(c) > biggest) biggest = contourArea(c), convexHull(c, hull);
        if (biggest > 0.1 * total) {
            Point2f r[4];
            minAreaRect(hull).points(r);
            std::vector<Point> box;
            for (auto& p : r) box.push_back(Point((int)std::min<float>(small.cols - 1, std::max<float>(0, p.x)),
                                                  (int)std::min<float>(small.rows - 1, std::max<float>(0, p.y))));
            consider(box);
        }
    }
    return best.empty() ? best : orderCorners(best);
}

Config loadConfig() {
    Config c;
    try {
        FileStorage f("config.json", FileStorage::READ | FileStorage::FORMAT_JSON);
        if (!f.isOpened()) return c;
        std::vector<float> p;
        f["corners"] >> p;
        if (p.size() == 8) {
            for (int i = 0; i < 4; i++) c.corners.push_back({p[2 * i], p[2 * i + 1]});
            c.corners = orderCorners(c.corners);
        }
        if (!f["exposure"].empty()) f["exposure"] >> c.exposure;
        if (!f["mic"].empty()) f["mic"] >> c.mic;
        if (!f["surface"].empty()) f["surface"] >> c.surface;
    } catch (const cv::Exception&) {  // unreadable config.json: warn and use the defaults
        fprintf(stderr, "WARNING: could not read config.json - using defaults\n");
        return Config();
    }
    return c;
}

volatile std::sig_atomic_t stopRequested = 0;  // set by Ctrl+C / web.py's stop

// Run a shell command and wait for it; returns its exit code. (std::system would ignore a Ctrl+C that arrives
// while the command runs, so a stop pressed at that moment would be lost.)
int runShell(const std::string& cmd) {
    pid_t pid = fork();
    if (pid == 0) {
        execl("/bin/sh", "sh", "-c", cmd.c_str(), (char*)nullptr);
        _exit(127);
    }
    if (pid < 0) return -1;
    int status = 0;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

// Find the USB camera. If its USB link drops for a moment it comes back under a new number (/dev/video2
// instead of /dev/video0), so it is looked up by its stable name (/dev/v4l/by-id/usb-...-video-index0), or
// else as the first USB video device. Returns "" while no camera is plugged in.
std::string findCamera() {
    if (const char* chosen = std::getenv("KNIGHTSCRIBE_CAMERA")) return fsys::exists(chosen) ? chosen : "";  // pick one by hand
    std::error_code ec;
    std::vector<std::string> found;
    for (auto& e : fsys::directory_iterator("/dev/v4l/by-id", ec)) {
        std::string n = e.path().string(), tail = "-video-index0";
        if (n.size() > tail.size() && n.compare(n.size() - tail.size(), tail.size(), tail) == 0) found.push_back(n);
    }
    if (found.empty())  // no stable name: any USB video device whose index is 0 (the Pi's own codec devices are not USB)
        for (auto& e : fsys::directory_iterator("/sys/class/video4linux", ec)) {
            std::string idx;
            std::ifstream(e.path() / "index") >> idx;
            if (idx == "0" && fsys::canonical(e.path() / "device", ec).string().find("usb") != std::string::npos)
                found.push_back("/dev/" + e.path().filename().string());
        }
    std::sort(found.begin(), found.end());
    return found.empty() ? "" : found[0];
}
std::string CAMERA = "/dev/video0";

void cameraSetting(const std::string& s) {  // sets one camera control with v4l2-ctl
    runShell("v4l2-ctl -d " + CAMERA + " -c " + s + " >/dev/null 2>&1");
}

void applyCamera(const Config& c) {
    cameraSetting("power_line_frequency=2");        // 60 Hz anti-flicker
    cameraSetting("exposure_dynamic_framerate=0");  // auto exposure may not drop below 30 fps...
    cameraSetting("exposure_auto_priority=0");      // ...(the same setting's name on older systems)
    cameraSetting(c.exposure == 0 ? "auto_exposure=3" : "auto_exposure=1");
    if (c.exposure) cameraSetting("exposure_time_absolute=" + std::to_string(c.exposure));
}

// Cut the teaching area out of the frame and straighten it into a flat rectangle.
// M (frame -> board) is returned too, so person boxes can be drawn on the board view.
Mat straighten(const Mat& frame, const Config& c, Mat& M) {
    std::vector<Point2f> src;
    for (auto p : c.corners) src.push_back({p.x * frame.cols, p.y * frame.rows});
    float w = std::max(norm(src[1] - src[0]), norm(src[2] - src[3]));
    float h = std::max(norm(src[3] - src[0]), norm(src[2] - src[1]));
    w = std::max(w, 32.f), h = std::max(h, 32.f);
    M = getPerspectiveTransform(src, std::vector<Point2f>{{0, 0}, {w, 0}, {w, h}, {0, h}});
    Mat out;
    warpPerspective(frame, out, M, Size(w, h));
    return out;
}

// Small COLOR copy (640 wide, lightly blurred) used for comparing frames. Color matters:
// yellow or light-blue marker barely changes brightness but changes one color channel a lot.
// Brightness is evened out (the board's white level is scaled to 200) so auto exposure
// brightening or darkening the whole picture doesn't look like the board changed.
Mat thumb(const Mat& board) {
    Mat t, g;
    resize(board, t, Size(640, std::max(1, 640 * board.rows / board.cols)), 0, 0, INTER_AREA);
    GaussianBlur(t, t, Size(3, 3), 0);
    cvtColor(t, g, COLOR_BGR2GRAY);
    int hist[256] = {0}, white = 0;  // 80th-percentile brightness = the board's white level
    for (auto it = g.begin<uchar>(); it != g.end<uchar>(); ++it) hist[*it]++;
    for (long sum = 0, target = g.total() * 8 / 10; white < 255 && (sum += hist[white]) < target; white++) {}
    t.convertTo(t, -1, 200.0 / std::max(white, 20));
    return t;
}

// Per pixel: the biggest of the B, G, R values (so a change in ANY color channel counts).
Mat maxChannel(const Mat& m) {
    std::vector<Mat> ch;
    split(m, ch);
    return max(max(ch[0], ch[1]), ch[2]);
}
Mat colorDiff(const Mat& a, const Mat& b) { Mat d; absdiff(a, b, d); return maxChannel(d); }
Mat darkerIn(const Mat& now, const Mat& before) { Mat d; subtract(before, now, d); return maxChannel(d); }

double fraction(const Mat& mask) { return countNonZero(mask) / (double)mask.total(); }

// The blank board's color at every pixel. "Closing" erases anything darker and thinner than
// a marker stroke but keeps bigger shapes, so it follows glare spots and shadows tightly.
Mat boardColor(const Mat& img) {
    int k = std::max(5, (img.cols / 52) | 1);  // a bit wider than a marker stroke
    Mat bg;
    GaussianBlur(img, bg, Size(), 1);
    morphologyEx(bg, bg, MORPH_CLOSE, getStructuringElement(MORPH_ELLIPSE, Size(k, k)));
    GaussianBlur(bg, bg, Size(), k / 7.0);
    return max(bg, img);  // the board is never darker than the pixel itself
}

// The middle of the teaching area: a selected area usually includes a strip of wall or the board's frame at
// its edges, which would otherwise look like writing (or like slide content) even on a blank surface.
Mat inner(const Mat& img) {
    int mx = img.cols / 25, my = img.rows / 25;  // 4% off each side
    return img(Rect(mx, my, img.cols - 2 * mx, img.rows - 2 * my));
}

// Board check: how much of the board is writing (darker than the board, in any color).
double ink(const Mat& small) {
    Mat mid = inner(small);
    return fraction(darkerIn(mid, boardColor(mid)) > INK_DIFF);
}

// Whiteboard cleaner: subtract the blank board so glare and shadows vanish. Glare ADDS light,
// so "how much darker than the board" survives it even when the stroke looks washed out.
// Then boost each area by its own stroke contrast (strokes under glare are fainter), drop
// camera noise, and put the marker on pure white with stronger colors.
const double CLEAN_NOISE = 7;          // ignore anything under 7 levels darker (camera noise)
const double CLEAN_MIN_CONTRAST = 28;  // never boost noise-level contrast all the way to black
const double CLEAN_BOLD = 1.6;         // higher = bolder strokes
const double CLEAN_SAT = 1.4;          // marker color boost
Mat cleanBoard(const Mat& img) {
    Mat f, bg, local, out;
    GaussianBlur(img, f, Size(), 0.7);
    f.convertTo(f, CV_32F);
    boardColor(img).convertTo(bg, CV_32F);
    Mat d = bg - f;                                    // how much darker than the board (B,G,R)
    local = max(maxChannel(d), 0.0);                   // strongest stroke contrast nearby...
    int k = std::max(5, (img.cols / 18) | 1);
    dilate(local, local, Mat::ones(k, k, CV_8U));
    GaussianBlur(local, local, Size(), img.cols / 73.0);
    Mat gain = CLEAN_BOLD / max(local, CLEAN_MIN_CONTRAST), gain3;  // ...sets the boost there
    merge(std::vector<Mat>{gain, gain, gain}, gain3);  // same boost for B,G,R keeps the color
    Mat s = d.reshape(1);                              // 1-channel view: math hits all 3 colors
    s = max(s - CLEAN_NOISE, 0.0);
    s = s.reshape(3).mul(gain3);
    s = min(s.reshape(1), 1.0);                        // stroke strength 0..1
    pow(s, 0.8, s);                                    // lift the faintest strokes
    Mat(255 * (1 - s)).reshape(3).convertTo(out, CV_8U);
    Mat hsv;
    cvtColor(out, hsv, COLOR_BGR2HSV);
    std::vector<Mat> ch;
    split(hsv, ch);
    ch[1].convertTo(ch[1], CV_8U, CLEAN_SAT);
    merge(ch, hsv);
    cvtColor(hsv, out, COLOR_HSV2BGR);
    return out;
}

// ---- slides / projector ----
// Slides are compared with a plain small copy: the whiteboard brightening in thumb() would turn a dark
// slide into noise.
Mat slideThumb(const Mat& board) {
    Mat t;
    resize(board, t, Size(640, std::max(1, 640 * board.rows / board.cols)), 0, 0, INTER_AREA);
    GaussianBlur(t, t, Size(3, 3), 0);
    return t;
}

// Auto mode: does the teaching area look like a projector / PowerPoint rather than a whiteboard?
// A whiteboard is bright, nearly colourless, and its writing is thin strokes. Slides are dark (dark theme or
// projector off), or have coloured areas (title bars, logos, charts) or big filled shapes (photos, diagrams).
// A plain white slide with only black text looks just like neat whiteboard writing: choose "slides" on the
// page for those (the text is read either way). Two sets of limits (hysteresis) so a borderline picture does
// not flip back and forth.
bool slideLike(const Mat& plain, bool wasSlide) {
    Mat inner = plain(Rect(plain.cols / 12, plain.rows / 12, plain.cols * 10 / 12, plain.rows * 10 / 12));  // skip the
    Mat hsv, g, closed;                                                     // edges: a hand-drawn box often includes wall
    cvtColor(inner, hsv, COLOR_BGR2HSV);
    Scalar m = mean(hsv);  // m[1] = colour strength, m[2] = brightness
    std::vector<Mat> ch;
    split(hsv, ch);
    double colour = fraction((ch[1] > 80) & (ch[2] > 60));  // share of clearly coloured pixels
    cvtColor(inner, g, COLOR_BGR2GRAY);
    // "closing" erases dark things thinner than ~1/40 of the width (marker strokes, text): only big shapes stay
    int k = std::max(9, (g.cols / 40) | 1);
    morphologyEx(g, closed, MORPH_CLOSE, getStructuringElement(MORPH_RECT, Size(k, k)));
    double white = mean(g)[0];
    { int hist[256] = {0}, w = 0;  // 80th-percentile brightness = the page / board white level
      for (auto it = g.begin<uchar>(); it != g.end<uchar>(); ++it) hist[*it]++;
      for (long sum = 0, target = g.total() * 8 / 10; w < 255 && (sum += hist[w]) < target; w++) {}
      white = w; }
    double bigDark = fraction(closed < white * 0.5);
    if (wasSlide) return !(m[2] > 125 && m[1] < 60 && colour < 0.05 && bigDark < 0.05);
    return m[2] < 100 || m[1] > 75 || colour > 0.10 || bigDark > 0.10;
}

// Is there anything on the surface? A blank screen or an empty page is flat; real content has contrast.
bool hasContent(const Mat& plain) {
    Mat g;
    cvtColor(inner(plain), g, COLOR_BGR2GRAY);
    Scalar mu, sd;
    meanStdDev(g, mu, sd);
    return sd[0] > 12;
}

// The outer 2% of a snapshot often holds a strip of wall or the board's frame. On a page with little text,
// that dark edge makes the text reader treat the whole picture as an image and read nothing, so it is cut off.
Mat trimEdges(const Mat& img) {
    int mx = img.cols / 50, my = img.rows / 50;
    return img(Rect(mx, my, img.cols - 2 * mx, img.rows - 2 * my)).clone();
}

// Text recognition works best on dark text on a light page, a bit enlarged. Slides often mix both: black
// text on white plus white titles on a coloured bar, or a whole dark theme. So every solid dark panel is
// flipped and the rest is left alone. A panel = a big region that is mostly dark even after its light
// lettering is filled in; a line of black text never counts, because most of it is the white between letters.
Mat forOcr(const Mat& board) {
    Mat g, dark, closed, labels, stats, centroids, flipped;
    cvtColor(board, g, COLOR_BGR2GRAY);
    if (g.cols < 1800) resize(g, g, Size(), 1.5, 1.5, INTER_CUBIC);
    dark = g < 110;
    int k = std::max(15, (g.cols / 60) | 1);  // wider than a letter stroke: fills light text inside a dark panel
    morphologyEx(dark, closed, MORPH_CLOSE, getStructuringElement(MORPH_RECT, Size(k, k)));
    int n = connectedComponentsWithStats(closed, labels, stats, centroids);
    bitwise_not(g, flipped);
    for (int i = 1; i < n; i++) {
        if (stats.at<int>(i, CC_STAT_AREA) < 0.01 * g.total()) continue;  // too small to be a panel
        Mat region = labels == i;
        if (countNonZero(dark & region) > 0.8 * countNonZero(region)) flipped.copyTo(g, region);
    }
    return trimEdges(g);
}

// NanoDet (OpenCV model zoo, models/nanodet.onnx): finds people (COCO class 0).
struct PersonDetector {
    dnn::Net net;
    std::vector<String> outs;
    bool ok = false;
    PersonDetector() {
        try {
            net = dnn::readNet("models/nanodet.onnx");
            outs = net.getUnconnectedOutLayersNames();
            ok = true;
        } catch (...) {
            fprintf(stderr, "WARNING: models/nanodet.onnx missing - person check is OFF\n");
        }
    }
    std::vector<Rect> find(const Mat& frame) {
        if (!ok) return {};
        float s = 416.f / std::max(frame.cols, frame.rows);  // fit inside 416x416, pad the rest
        Mat small, pad = Mat::zeros(416, 416, CV_8UC3);
        resize(frame, small, Size(), s, s, INTER_AREA);
        small.copyTo(pad(Rect(0, 0, small.cols, small.rows)));
        pad.convertTo(pad, CV_32F);
        subtract(pad, Scalar(103.53, 116.28, 123.675), pad);
        divide(pad, Scalar(57.375, 57.12, 58.395), pad);
        net.setInput(dnn::blobFromImage(pad));
        std::vector<Mat> o;
        net.forward(o, outs);
        std::map<int, Mat> cls, reg;  // grid cells -> scores (80 classes) / box distances (4x8)
        for (auto& m : o) (m.size[2] == 80 ? cls : reg)[m.size[1]] = Mat(m.size[1], m.size[2], CV_32F, m.ptr<float>());
        std::vector<Rect> boxes;
        std::vector<float> scores;
        for (auto& [n, c] : cls) {
            int g = (int)std::lround(std::sqrt(n)), stride = 416 / g;
            for (int i = 0; i < n; i++) {
                float score = c.at<float>(i, 0);  // class 0 = person
                if (score < PERSON_SCORE) continue;
                float cx = (i % g) * stride + 0.5f * (stride - 1), cy = (i / g) * stride + 0.5f * (stride - 1), d[4];
                for (int k = 0; k < 4; k++) {  // each side's distance is a softmax over 8 bins
                    const float* v = reg[n].ptr<float>(i) + 8 * k;
                    float top = *std::max_element(v, v + 8), sum = 0, avg = 0;
                    for (int j = 0; j < 8; j++) sum += std::exp(v[j] - top), avg += std::exp(v[j] - top) * j;
                    d[k] = avg / sum * stride;
                }
                boxes.push_back(Rect(Point((cx - d[0]) / s, (cy - d[1]) / s), Point((cx + d[2]) / s, (cy + d[3]) / s)));
                scores.push_back(score);
            }
        }
        std::vector<int> keep;
        dnn::NMSBoxes(boxes, scores, PERSON_SCORE, 0.5f, keep);
        std::vector<Rect> people;
        for (int i : keep)
            if (boxes[i].height > frame.rows * 0.15) people.push_back(boxes[i]);  // skip tiny ones
        return people;
    }
};

std::string timestamp(const char* fmt) {
    char buf[64];
    time_t now = time(nullptr);
    strftime(buf, sizeof buf, fmt, localtime(&now));
    return buf;
}

void renameQuiet(const std::string& from, const std::string& to) {  // a failed rename must never stop the program
    std::error_code ec;
    fsys::rename(from, to, ec);
}

void writeAtomic(const std::string& path, const Mat& img) {  // page never sees half a file
    if (imwrite(path + ".tmp.jpg", img, {IMWRITE_JPEG_QUALITY, 75})) renameQuiet(path + ".tmp.jpg", path);
}

int main(int argc, char** argv) {
    bool record = argc > 1 && std::string(argv[1]) == "record";
    // Ctrl+C (or web.py's stop) only reaches this program: ffmpeg runs in its own process group. This program
    // then passes exactly ONE Ctrl+C on to ffmpeg, which finishes its files cleanly (a second one would make
    // it quit at once and leave the video unfinished); when ffmpeg closes the pipe, the loops below end.
    std::signal(SIGINT, [](int) { stopRequested = 1; });
    std::signal(SIGTERM, [](int) { stopRequested = 1; });

    // camera unplugged (or its USB link dropped)? wait here until it is back, instead of failing
    for (bool told = false; (CAMERA = findCamera()).empty(); told = true) {
        if (stopRequested) return 0;
        if (!told) fprintf(stderr, "No camera found - waiting for it (check the USB cable)\n");
        std::ofstream("status.json.tmp") << "{\"state\":\"camera_unplugged\",\"recording\":false}";
        renameQuiet("status.json.tmp", "status.json");
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    Config cfg = loadConfig();
    applyCamera(cfg);
    PersonDetector detector;
    bool ocr = runShell("command -v tesseract >/dev/null 2>&1") == 0;

    // ---- start ffmpeg: camera (+mic) in; recordings + live video + raw frames out ----
    if (stopRequested) return 0;  // stopped while starting up: don't start ffmpeg (or make an empty lecture)
    std::string lecture = timestamp("%Y-%m-%d_%H-%M-%S"), dir = "lectures/" + lecture;
    std::string cmd =
        "ffmpeg -nostdin -y -hide_banner -loglevel error -f v4l2 -input_format mjpeg"
        " -video_size " + std::to_string(W) + "x" + std::to_string(H) +
        " -framerate 30 -thread_queue_size 512 -i " + CAMERA;
    if (record) {
        fsys::create_directories(dir + "/snapshots");
        fsys::create_directories(dir + "/chunks");
        if (!cfg.mic.empty()) cmd += " -f alsa -thread_queue_size 1024 -i " + cfg.mic;
        cmd += " -map 0:v -c:v h264_v4l2m2m -pix_fmt yuv420p -b:v 8M -g 60"
               " -f segment -segment_time 300 -reset_timestamps 1 " + dir + "/video_%03d.mkv";
        if (!cfg.mic.empty()) {
            cmd += " -map 1:a -ac 1 -c:a flac " + dir + "/audio.flac";
            // 16 kHz mono is what Whisper wants; a chunk is complete once the next one starts
            cmd += " -map 1:a -ac 1 -ar 16000 -c:a pcm_s16le -f segment -segment_time " +
                   std::to_string(CHUNK_SECONDS) + " -reset_timestamps 1 " + dir + "/chunks/chunk_%05d.wav";
            // live draft captions: raw audio over UDP (never blocks ffmpeg, even if nobody listens)
            cmd += " -map 1:a -ac 1 -ar 16000 -c:a pcm_s16le -f s16le \"udp://127.0.0.1:5005?pkt_size=1280\"";
        }
    }
    // The camera already sends JPEG pictures, so the page's live video just copies them (no decoding, no
    // re-encoding): a smooth 30 fps preview for almost no CPU. mjpeg2jpeg makes every picture a normal JPEG.
    cmd += " -map 0:v -c:v copy -bsf:v mjpeg2jpeg -f image2 -update 1 -atomic_writing 1 " + LIVE_JPG;
    const int visionFps = record ? VISION_FPS : PREVIEW_FPS;  // detector checks per second
    cmd += " -map 0:v -vf fps=" + std::to_string(visionFps) + " -pix_fmt bgr24 -f rawvideo pipe:1";
    int fds[2];
    if (::pipe(fds) != 0) {
        fprintf(stderr, "ERROR: could not start ffmpeg\n");
        return 1;
    }
    pid_t parent = getpid(), ffmpeg = fork();
    if (ffmpeg == 0) {
        setpgid(0, 0);                    // own process group: a Ctrl+C meant for this program does not hit it twice
        prctl(PR_SET_PDEATHSIG, SIGINT);  // if this program dies, ffmpeg still gets one Ctrl+C and closes its files
        if (getppid() != parent) _exit(1);
        dup2(fds[1], 1);
        close(fds[0]), close(fds[1]);
        execl("/bin/sh", "sh", "-c", ("exec " + cmd).c_str(), (char*)nullptr);
        _exit(127);
    }
    close(fds[1]);
    FILE* pipe = ffmpeg > 0 ? fdopen(fds[0], "r") : nullptr;
    if (!pipe) {
        fprintf(stderr, "ERROR: could not start ffmpeg\n");
        return 1;
    }
    std::ofstream("ffmpeg.pid") << ffmpeg;  // lets web.py clean up if this program is ever killed
    printf("%s\n", record ? ("Recording to " + dir + "  (Ctrl+C to stop)").c_str()
                          : "Preview mode - nothing is saved");

    // ---- reader thread: always pulls frames so ffmpeg never waits on us ----
    std::mutex m;
    Mat latest;
    long latestNum = -1;
    std::atomic<bool> done{false};
    std::thread reader([&] {
        Mat buf(H, W, CV_8UC3);
        for (long n = 0; fread(buf.data, 1, buf.total() * 3, pipe) == buf.total() * 3; n++) {
            std::lock_guard<std::mutex> lock(m);
            buf.copyTo(latest);
            latestNum = n;
        }
        done = true;
    });
    // The detector works at low priority and on at most 2 cores, so its checks never take CPU time from ffmpeg
    // (which keeps the camera, the recording and the live picture going). On Linux this applies to this thread
    // and everything it starts from here on (OpenCV's worker threads, the text reader).
    setpriority(PRIO_PROCESS, 0, 10);
    cv::setNumThreads(2);

    // ---- detector loop: look at the newest frame ----
    Mat prev, prevPlain;  // comparison copies of the previous frame
    std::map<std::string, Mat> lastSnap;  // comparison copy of the last snapshot, one per kind, so switching
                                          // between board and slides and back does not save the same picture twice
    int stillCount = 0, saved = 0, occlusions = 0, votes = 0, errors = 0;
    bool blocked = false;
    long seen = -1;
    std::string lastSaved, lastKind, prevKind, curKind;  // kinds: "whiteboard" or "slide"
    bool autoSlides = false;                              // auto mode: is the surface a projector right now?
    // when config.json was last changed (the file may not exist yet, or vanish mid-check)
    auto configTime = [] {
        std::error_code ec;
        auto t = fsys::last_write_time("config.json", ec);
        return ec ? fsys::file_time_type{} : t;
    };
    auto cfgTime = configTime();
    std::ofstream index;
    if (record) {
        index.open(dir + "/snapshots.csv");
        index << "seconds,file,kind\n" << std::flush;
    }

    // Save one snapshot: original + cleaned copy + OCR text. In preview mode nothing is written.
    auto save = [&](const Mat& board, const Mat& small, double when, const std::string& kind) {
        lastSnap[kind] = small;
        if (!record) return std::string("ready (not recording - nothing saved)");
        char name[32];
        snprintf(name, sizeof name, "snap_%06.1f", when);
        std::string base = dir + "/snapshots/" + name;
        // text reading runs on 1 core at low priority: it must never stall the recording
        const std::string lowPriority = "(OMP_THREAD_LIMIT=1 nice -n 15 tesseract ";
        if (kind == "slide") {
            imwrite(base + "_clean.jpg", board);  // slides need no cleaning (the page uses this name for its pictures)
            imwrite(base + ".jpg", board);        // written last = "ready"
            if (ocr && imwrite(base + "_ocr.png", forOcr(board)))  // slide text -> snap_XXXX.txt, in the background
                runShell(lowPriority + base + "_ocr.png " + base + " --psm 3 >/dev/null 2>&1; rm -f " + base + "_ocr.png) &");
        } else {
            Mat clean = cleanBoard(board);
            imwrite(base + "_clean.jpg", clean);  // cleaned + saturated
            imwrite(base + ".jpg", board);        // the original (written last = "ready")
            if (ocr && imwrite(base + "_ocr.png", trimEdges(clean)))  // whiteboard text -> snap_XXXX.txt, in the background
                runShell(lowPriority + base + "_ocr.png " + base + " --psm 6 >/dev/null 2>&1; rm -f " + base + "_ocr.png) &");
        }
        index << when << "," << name << ".jpg," << kind << std::endl;
        lastSaved = name, lastKind = kind, saved++;
        return std::string("saved");
    };

    bool forwarded = false;
    // camera watchdog: if no picture arrives for STALL_SECONDS the camera has hung (USB hiccup, loose cable).
    // Then ffmpeg is told to stop (it closes the recording files) and this program ends; web.py starts it again
    // right away, which resets the camera.
    const int STALL_SECONDS = 6;
    auto lastFrame = std::chrono::steady_clock::now(), stalledAt = lastFrame;
    bool stalled = false;
    while (!done) {
        if (stopRequested && !forwarded) forwarded = true, kill(ffmpeg, SIGINT);  // pass the stop on, exactly once
        Mat frame;
        long num;
        {
            std::lock_guard<std::mutex> lock(m);
            num = latestNum;
            if (num != seen) frame = latest.clone();
        }
        if (num == seen) {
            auto now = std::chrono::steady_clock::now();
            if (!stalled && now - lastFrame > std::chrono::seconds(STALL_SECONDS)) {
                stalled = true, stalledAt = now;
                fprintf(stderr, "camera sent no picture for %d s - restarting it\n", STALL_SECONDS);
                std::ofstream("status.json.tmp") << "{\"state\":\"camera_stalled\",\"recording\":" << (record ? "true" : "false")
                                                 << ",\"lecture\":\"" << (record ? lecture : "") << "\"}";
                renameQuiet("status.json.tmp", "status.json");
                if (!forwarded) forwarded = true, kill(ffmpeg, SIGINT);  // ffmpeg finishes its files and quits;
            }                                                            // the reader then ends this loop
            if (stalled && now - stalledAt > std::chrono::seconds(8)) {  // ffmpeg is stuck too: force it
                fprintf(stderr, "ffmpeg did not stop - forcing it\n");
                kill(ffmpeg, SIGKILL);
                stalledAt = now;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            continue;
        }
        seen = num, lastFrame = std::chrono::steady_clock::now();
        double t = num / (double)visionFps;  // seconds on the recording's clock
        int64 tick = getTickCount();
        std::string state;
        double motion = 0, change = 0, inkAmount = 0;
        Mat view;  // the debug view the page shows under "Visual Detector"

        // Everything below is guarded: a bad frame or a bad setting must never end the program, because
        // ending it would also cut the recording short.
        try {
        std::error_code ec;
        if (fsys::exists("autoselect.request", ec)) {  // the teacher pressed "Auto-find board" on the page
            fsys::remove("autoselect.request", ec);
            std::vector<Point2f> found = findBoard(frame);
            {
                std::ofstream out("autoselect.json.tmp");
                out << "{\"found\":" << (found.empty() ? "false" : "true") << ",\"points\":[";
                for (size_t i = 0; i < found.size(); i++) out << (i ? "," : "") << found[i].x << "," << found[i].y;
                out << "]}";
            }
            renameQuiet("autoselect.json.tmp", "autoselect.json");
        }

        // web page saved new settings? reload them and start the detector over
        if (configTime() != cfgTime) {
            cfgTime = configTime();
            cfg = loadConfig();
            applyCamera(cfg);
            prev.release(), prevPlain.release(), lastSnap.clear(), stillCount = 0, votes = 0, prevKind.clear();
        }

        if (cfg.corners.empty()) {
            state = "waiting_for_roi";
            curKind.clear();
            resize(frame, view, Size(720, 405));
        } else {
            Mat M, board = straighten(frame, cfg, M), plain = slideThumb(board);
            bool slides = cfg.surface == "slides";
            if (cfg.surface == "auto") {
                // the decision only changes after the picture has looked different for 3 s while nobody is
                // moving in front of it, so a teacher walking past never flips it
                bool looks = slideLike(plain, autoSlides);
                bool calm = !prevPlain.empty() && prevPlain.size() == plain.size() &&
                            fraction(colorDiff(plain, prevPlain) > MOTION_DIFF) < 0.01;
                if (prevKind.empty()) autoSlides = looks, votes = 0;  // first look: decide right away
                else if (looks == autoSlides) votes = 0;
                else if (calm && ++votes >= 3 * visionFps) autoSlides = looks, votes = 0;
                slides = autoSlides;
            }
            prevPlain = plain;
            std::string kind = slides ? "slide" : "whiteboard";
            Mat small = slides ? plain : thumb(board);  // the copy that frames are compared with
            if (kind != prevKind) prev.release(), stillCount = 0, prevKind = kind;
            curKind = kind;
            Mat& last = lastSnap[kind];
            resize(board, view, Size(720, std::max(1, 720 * board.rows / board.cols)));
            auto paint = [&](const Mat& mask, Scalar color) {  // tint the masked pixels
                Mat big, tint(view.size(), view.type(), color), mix;
                resize(mask, big, view.size(), 0, 0, INTER_NEAREST);
                addWeighted(view, 0.35, tint, 0.65, 0, mix);
                mix.copyTo(view, big);
            };
            Mat diff;
            if (!prev.empty() && prev.size() == small.size()) {
                diff = colorDiff(small, prev);
                motion = fraction(diff > MOTION_DIFF);
                paint(diff > MOTION_DIFF, Scalar(0, 0, 255));  // red = moving right now
            }
            prev = small;
            if (!last.empty() && last.size() != small.size()) last.release();  // the area was changed
            stillCount = (!diff.empty() && motion < STILL) ? stillCount + 1 : 0;
            if (stillCount < STILL_SECONDS * visionFps) {
                state = stillCount ? "stabilizing" : "changing";
            } else if (votes > 0) {  // auto mode is about to switch between board and slides: wait for it, so
                state = "checking_surface";  // the picture is saved once, as the right kind
            } else if (!record) {  // preview: the person check, snapshots and text reading wait for a recording
                state = "ready_when_recording";
            } else {  // board is still: now (and only now) do the heavier checks
                bool blank, newWriting;
                if (slides) {  // a new slide: a big part of the screen differs from the last saved picture
                    blank = !hasContent(plain);
                    if (!last.empty()) {
                        Mat changed = colorDiff(small, last) > INK_DIFF;
                        change = fraction(changed);
                        paint(changed, Scalar(0, 255, 0));  // green = different from the last saved slide
                    }
                    newWriting = !blank && (last.empty() || change >= SLIDE_CHANGE);
                } else {
                    inkAmount = ink(small);
                    if (!last.empty()) {  // NEW writing only (darker than the last snapshot); erasing doesn't count
                        Mat added = darkerIn(small, last) > INK_DIFF;
                        change = fraction(added);
                        paint(added, Scalar(0, 255, 0));                             // green = new content
                        paint(darkerIn(last, small) > INK_DIFF, Scalar(255, 0, 0));  // blue  = erased
                    }
                    blank = inkAmount < MIN_INK;
                    newWriting = !blank && (last.empty() || change >= NEW_CONTENT);
                }
                if (!newWriting) {
                    state = blank ? (slides ? "blank_screen" : "blank_board") : "stable";
                } else {
                    std::vector<Point> area;
                    for (auto p : cfg.corners) area.push_back(Point(p.x * frame.cols, p.y * frame.rows));
                    bool personInWay = false;
                    for (auto& r : detector.find(frame)) {
                        if ((r & boundingRect(area)).area() == 0) continue;
                        personInWay = true;  // draw the person on the board view in orange
                        std::vector<Point2f> box{Point2f(r.x, r.y), Point2f(r.br().x, r.y), Point2f(r.br().x, r.br().y), Point2f(r.x, r.br().y)}, onBoard;
                        perspectiveTransform(box, onBoard, M);
                        std::vector<Point> poly;
                        for (auto q : onBoard) poly.push_back(Point(q.x * view.cols / board.cols, q.y * view.rows / board.rows));
                        polylines(view, poly, true, Scalar(0, 140, 255), 4);
                    }
                    if (personInWay) {
                        state = "person_blocking";
                        if (!blocked) occlusions++;
                    } else {
                        state = save(board, small, t, kind);
                    }
                    blocked = personInWay;
                }
            }
        }
        } catch (const std::exception& e) {  // note it, show it on the page, and carry on with the next frame
            if (errors++ < 20) fprintf(stderr, "detector error (recording continues): %s\n", e.what());
            state = "error";
            prev.release(), prevPlain.release(), stillCount = 0;
            if (frame.empty()) frame = Mat::zeros(H, W, CV_8UC3);
            resize(frame, view, Size(720, 405));
        }
        if (state != "person_blocking") blocked = false;

        // debug view + status for the web page
        putText(view, "State: " + state, Point(12, 28), FONT_HERSHEY_SIMPLEX, 0.7, Scalar(0, 0, 0), 4, LINE_AA);
        putText(view, "State: " + state, Point(12, 28), FONT_HERSHEY_SIMPLEX, 0.7, Scalar(0, 255, 255), 2, LINE_AA);
        writeAtomic("debug.jpg", view);
        int ms = (int)((getTickCount() - tick) * 1000 / getTickFrequency());
        {
            std::ofstream("status.json.tmp")
                << "{\"state\":\"" << state << "\",\"recording\":" << (record ? "true" : "false")
                << ",\"lecture\":\"" << (record ? lecture : "") << "\",\"seconds\":" << t
                << ",\"motion\":" << motion * 100 << ",\"change\":" << change * 100 << ",\"ink\":" << inkAmount * 100
                << ",\"saved\":" << saved << ",\"last_saved\":\"" << lastSaved << "\",\"occlusions\":" << occlusions
                << ",\"ms\":" << ms << ",\"person_model\":" << (detector.ok ? "true" : "false")
                << ",\"ocr\":" << (ocr ? "true" : "false")
                << ",\"surface\":\"" << curKind << "\",\"last_kind\":\"" << lastKind << "\""
                << ",\"errors\":" << errors
                << ",\"width\":" << W << ",\"height\":" << H << ",\"camera_fps\":" << 30 << "}";
        }
        renameQuiet("status.json.tmp", "status.json");
    }

    reader.join();
    fclose(pipe);
    while (waitpid(ffmpeg, nullptr, 0) < 0 && errno == EINTR) {}
    std::error_code ec;
    fsys::remove("ffmpeg.pid", ec);
    if (record) std::ofstream(dir + "/chunks/DONE") << "1";  // tells transcribe.py the audio is complete
    printf("Stopped.%s\n", record ? (" " + std::to_string(saved) + " snapshots saved in " + dir).c_str() : "");
    return 0;
}
