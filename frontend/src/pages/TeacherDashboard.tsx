import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type {
  Course,
  Lecture,
  ReferenceMaterial,
  CourseSettings,
} from "../data/mockData";
import { parseTranscript, generateFromTranscript } from "../api";
import { createQuizQuestion, generateQuiz, generateSummary, uploadDocument } from "../backend";
import CourseSettingsPanel from "../components/CourseSettingsPanel";

// ===================== Raspberry Pi (Jack's web.py) =====================
// web.py runs on the Pi and controls the camera; this page only sends it
// requests. The Render backend lives in backend.ts.

const PI_BASE = ((import.meta.env.VITE_PI_BASE_URL as string | undefined) ?? "")
  .trim()
  .replace(/\/$/, "");

const PI_HOST = (() => {
  try {
    return new URL(PI_BASE).host;
  } catch {
    return "the Pi";
  }
})();

// Jack's own page, with board area, exposure and export controls
const piPageUrl = PI_BASE;

// Live picture for the teacher's preview
const piVideoUrl =
  ((import.meta.env.VITE_PI_STREAM_URL as string | undefined) ?? "").trim() ||
  (PI_BASE ? `${PI_BASE}/video` : "");

const STATUS_TIMEOUT_MS = 4000;
// Starting or stopping restarts the capture program, and stopping waits for
// the recording files to close, so give it time.
const ACTION_TIMEOUT_MS = 45000;

type CameraState = "ok" | "starting" | "reconnecting" | "unplugged";

type PiStatus =
  | {
      online: true;
      recording: boolean;
      lecture: string | null;
      seconds: number | null; // time into the recording
      camera: CameraState;
      tempC: number | null;
      hoursLeft: number | null; // storage left for recording
    }
  | { online: false; reason: string };

async function call(
  method: "GET" | "POST",
  path: string,
  timeoutMs: number,
  body?: unknown
) {
  if (!PI_BASE) {
    throw new Error("VITE_PI_BASE_URL is not set in frontend/.env.");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(
      `${PI_BASE}${path}`,
      body === undefined
        ? { method, signal: controller.signal }
        : {
            method,
            signal: controller.signal,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
    );
  } catch {
    // The browser reports "unreachable" and "blocked by CORS" the same way.
    throw new Error(
      controller.signal.aborted
        ? `${PI_HOST} took too long to answer.`
        : `Can't reach the camera at ${PI_HOST}. Check that the Pi is on, ` +
            `this laptop is on the same Wi-Fi, and web.py is running.`
    );
  } finally {
    clearTimeout(timer);
  }

  let data: { message?: string; [key: string]: unknown } = {};
  try {
    data = await res.json();
  } catch {
    // some error pages aren't JSON
  }
  if (!res.ok) {
    throw new Error(data.message ?? `The camera answered with error ${res.status}.`);
  }
  return data;
}

// Never throws: an unreachable Pi comes back as { online: false }.
async function getPiStatus(): Promise<PiStatus> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const s: any = await call("GET", "/status", STATUS_TIMEOUT_MS);
    const det = s.detector ?? {};
    const sys = s.system ?? {};

    let camera: CameraState = "ok";
    if (det.state === "camera_unplugged" || sys.camera_plugged === false) {
      camera = "unplugged";
    } else if (det.state === "camera_stalled") {
      camera = "reconnecting";
    } else if (!s.running || det.state === "starting" || sys.camera_ok === false) {
      camera = "starting";
    }

    return {
      online: true,
      recording: !!s.recording,
      lecture: s.recording ? det.lecture || s.lecture || null : null,
      seconds: typeof det.seconds === "number" ? det.seconds : null,
      camera,
      tempC: typeof sys.temp_c === "number" ? sys.temp_c : null,
      hoursLeft: typeof sys.hours_left === "number" ? sys.hours_left : null,
    };
  } catch (err) {
    return { online: false, reason: (err as Error).message };
  }
}

// Both return Jack's message, e.g. "Recording started.", or throw a
// plain-words error. With a title, the Pi's cloud.py creates the lecture on
// the backend under that title and course.
async function startRecording(lecture?: {
  title: string;
  course_id: number;
}): Promise<string> {
  const data = await call("POST", "/record/start", ACTION_TIMEOUT_MS, lecture);
  return data.message ?? "Recording started.";
}

async function stopRecording(): Promise<string> {
  const data = await call("POST", "/record/stop", ACTION_TIMEOUT_MS);
  return data.message ?? "Recording stopped.";
}

const POLL_MS = 3000;

const cameraText: Record<CameraState, string> = {
  ok: "Working",
  starting: "Starting...",
  reconnecting: "Reconnecting...",
  unplugged: "Unplugged, check the USB cable",
};

// 75 -> "1:15", 3725 -> "1:02:05"
function clock(total: number) {
  const s = Math.floor(total);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

// Teacher only: shows the classroom Pi and starts / stops the recording.
function PiControlPanel() {
  const [status, setStatus] = useState<PiStatus | null>(null);
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [confirmingStop, setConfirmingStop] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null
  );

  // Check the Pi every few seconds. The next check waits for the last one,
  // so a slow Pi never gets a pile of requests.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    async function check() {
      const next = await getPiStatus();
      if (cancelled) return;
      setStatus(next);
      timer = window.setTimeout(check, POLL_MS);
    }
    check();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  async function run(kind: "start" | "stop", action: () => Promise<string>) {
    setBusy(kind);
    setConfirmingStop(false);
    setMessage(null);
    try {
      setMessage({ ok: true, text: await action() });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setStatus(await getPiStatus());
      setBusy(null);
    }
  }

  const online = status?.online === true;
  const recording = online && status.recording;

  return (
    <div className="teacher-panel pi-panel">
      <div className="pi-header">
        <h3>Camera / Lecture control</h3>
        <span
          className={
            status === null ? "pi-pill" : online ? "pi-pill online" : "pi-pill offline"
          }
        >
          {status === null ? "Checking..." : online ? "Online" : "Offline"}
        </span>
      </div>

      {status === null && <p className="pi-dim">Looking for the classroom camera...</p>}

      {status && !status.online && <p className="pi-error">{status.reason}</p>}

      {status?.online && (
        <>
          <dl className="pi-facts">
            <dt>Recording</dt>
            <dd>
              {status.recording ? (
                <span className="pi-rec">
                  <span className="live-dot" />
                  Yes
                  {status.seconds !== null && ` · ${clock(status.seconds)}`}
                  {status.lecture && ` · ${status.lecture}`}
                </span>
              ) : (
                "No"
              )}
            </dd>
            <dt>Camera</dt>
            <dd className={status.camera === "ok" ? "" : "pi-warn"}>
              {cameraText[status.camera]}
            </dd>
            {(status.tempC !== null || status.hoursLeft !== null) && (
              <>
                <dt>Pi</dt>
                <dd>
                  {[
                    status.tempC !== null && `${status.tempC} °C`,
                    status.hoursLeft !== null &&
                      `${status.hoursLeft} h of storage left`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </dd>
              </>
            )}
          </dl>

          {piVideoUrl && status.camera === "ok" && (
            <img className="pi-preview" src={piVideoUrl} alt="Classroom camera" />
          )}
        </>
      )}

      <div className="pi-actions">
        {!recording && !confirmingStop && (
          <button
            className="teacher-btn primary"
            disabled={!online || busy !== null}
            onClick={() => run("start", () => startRecording())}
          >
            {busy === "start" ? "Starting..." : "Start recording"}
          </button>
        )}

        {recording && !confirmingStop && (
          <button
            className="teacher-btn solid-danger"
            disabled={busy !== null}
            onClick={() => setConfirmingStop(true)}
          >
            {busy === "stop" ? "Stopping..." : "Stop recording"}
          </button>
        )}

        {confirmingStop && (
          <div className="pi-confirm">
            <p>End the lecture? The recording will stop and be saved.</p>
            <button
              className="teacher-btn solid-danger"
              disabled={busy !== null}
              onClick={() => run("stop", stopRecording)}
            >
              Yes, stop recording
            </button>
            <button
              className="teacher-btn"
              disabled={busy !== null}
              onClick={() => setConfirmingStop(false)}
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {busy === "stop" && (
        <p className="pi-dim">Closing the recording files, this can take a few seconds...</p>
      )}

      {message && (
        <p className={message.ok ? "pi-message" : "pi-error"}>{message.text}</p>
      )}

      {piPageUrl && (
        <a className="pi-link" href={piPageUrl} target="_blank" rel="noreferrer">
          Open the full camera setup page ↗
        </a>
      )}
    </div>
  );
}

// ========================= Teacher dashboard =========================

interface TeacherDashboardProps {
  course: Course;
  lectures: Lecture[];
  setLectures: Dispatch<SetStateAction<Lecture[]>>;
  references: ReferenceMaterial[];
  setReferences: Dispatch<SetStateAction<ReferenceMaterial[]>>;
  settings: CourseSettings;
  setSettings: (settings: CourseSettings) => void;
  onRefresh: () => void; // reload the lectures from the backend now
}
// Accepts watch, youtu.be, live, and embed links and returns an embed URL
function toEmbedUrl(url: string): string | null {
  const match = url.match(/(?:v=|youtu\.be\/|embed\/|live\/)([A-Za-z0-9_-]{11})/);
  return match ? `https://www.youtube.com/embed/${match[1]}` : null;
}

function TeacherDashboard({
  course,
  lectures,
  setLectures,
  references,
  setReferences,
  settings,
  setSettings,
  onRefresh,
}: TeacherDashboardProps) {
  const [source, setSource] = useState<"camera" | "youtube">("camera");
  const [notice, setNotice] = useState("");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [transcriptText, setTranscriptText] = useState("");
  const [isLive, setIsLive] = useState(false);
  const [published, setPublished] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  // Classroom camera: start recording on the Pi. Its cloud.py creates the
  // lecture on the backend, and the auto-refresh brings it into the list.
  async function handleStartCamera() {
    if (!title.trim()) {
      setError("Give the lecture a title.");
      return;
    }
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const reply = await startRecording({ title: title.trim(), course_id: course.id });
      if (reply === "Already recording.") {
        setError(
          "The camera is already recording a lecture. Stop it in Camera / Lecture control first."
        );
      } else {
        setNotice(`"${title.trim()}" is starting. It appears under Your lectures in a few seconds.`);
        setTitle("");
        window.setTimeout(onRefresh, 4000); // cloud.py checks every 3 seconds
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // YouTube: a lecture that lives only in this browser
  async function handleAdd() {
    const embedUrl = toEmbedUrl(url);
    if (!title.trim()) {
      setError("Give the lecture a title.");
      return;
    }
    if (!embedUrl) {
      setError("That doesn't look like a YouTube link.");
      return;
    }

    setError("");
    setNotice("");
    setBusy(true);

    const transcript = parseTranscript(transcriptText);
    const generated =
      transcript.length > 0
        ? await generateFromTranscript(transcript)
        : { liveSummary: [], quiz: [] };

    const newLecture: Lecture = {
      id: Date.now(),
      courseId: course.id,
      local: true,
      title: title.trim(),
      videoUrl: embedUrl,
      isLive,
      published,
      completed: false,
      transcript,
      liveSummary: generated.liveSummary,
      quiz: generated.quiz,
    };

    setLectures((prev) => [...prev, newLecture]);
    setTitle("");
    setUrl("");
    setTranscriptText("");
    setBusy(false);
  }

  function toggleLive(id: number) {
    setLectures((prev) =>
      prev.map((l) => (l.id === id ? { ...l, isLive: !l.isLive } : l))
    );
  }

  function togglePublished(id: number) {
    setLectures((prev) =>
      prev.map((l) => (l.id === id ? { ...l, published: !l.published } : l))
    );
  }

  function handleDelete(id: number) {
    setLectures((prev) => prev.filter((l) => l.id !== id));
    setConfirmDeleteId(null);
  }

  // Reference material goes to the backend, where its text is searchable and
  // the AI chatbot can cite it.
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function handleTextbook(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setUploadMsg(null);
    try {
      const doc = await uploadDocument(course.id, file);
      setReferences((prev) => [...prev, doc]);
      setUploadMsg({ ok: true, text: `"${doc.title}" uploaded. Students and the AI can use it now.` });
    } catch (err) {
      setUploadMsg({ ok: false, text: (err as Error).message });
    } finally {
      setUploading(false);
    }
  }

  // AI summary / quiz for one lecture, on request (the Pi also asks for them automatically)
  const [aiBusy, setAiBusy] = useState<{ id: number; kind: "summary" | "quiz" } | null>(null);
  const [aiMsg, setAiMsg] = useState<{ id: number; ok: boolean; text: string } | null>(null);

  async function runAI(lecture: Lecture, kind: "summary" | "quiz") {
    if (!lecture.backendId || aiBusy) return;
    setAiBusy({ id: lecture.id, kind });
    setAiMsg(null);
    try {
      if (kind === "summary") {
        const n = await generateSummary(lecture.backendId, !lecture.isLive);
        setAiMsg({ id: lecture.id, ok: true, text: n ? `Summary written (${n} points).` : "The AI found nothing to summarize yet." });
        onRefresh();
      } else {
        const n = await generateQuiz(lecture.backendId);
        setAiMsg({ id: lecture.id, ok: true, text: n ? `${n} practice questions added.` : "The AI couldn't write questions from this lecture." });
      }
    } catch (err) {
      setAiMsg({ id: lecture.id, ok: false, text: (err as Error).message });
    } finally {
      setAiBusy(null);
    }
  }

  // Practice questions for a lecture (until the AI writes them)
  const quizLectures = lectures.filter((l) => l.backendId);
  const [quizLecture, setQuizLecture] = useState("");
  const [quizText, setQuizText] = useState("");
  const [quizOptions, setQuizOptions] = useState(["", "", "", ""]);
  const [quizCorrect, setQuizCorrect] = useState(0);
  const [quizExplanation, setQuizExplanation] = useState("");
  const [quizBusy, setQuizBusy] = useState(false);
  const [quizMsg, setQuizMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function handleAddQuestion() {
    const lectureId = quizLecture || quizLectures[0]?.backendId;
    const filled = quizOptions.map((o) => o.trim());
    const options = filled.filter(Boolean);
    if (!lectureId) return setQuizMsg({ ok: false, text: "There is no lecture to add a question to yet." });
    if (!quizText.trim()) return setQuizMsg({ ok: false, text: "Write the question first." });
    if (options.length < 2) return setQuizMsg({ ok: false, text: "Give at least two answer options." });
    if (!filled[quizCorrect]) return setQuizMsg({ ok: false, text: "The correct answer can't be an empty option." });
    // the correct answer's position once empty options are left out
    const correctOption = filled.slice(0, quizCorrect).filter(Boolean).length;
    setQuizBusy(true);
    setQuizMsg(null);
    try {
      await createQuizQuestion(lectureId, {
        question: quizText.trim(),
        options,
        correctOption,
        explanation: quizExplanation.trim(),
      });
      setQuizMsg({ ok: true, text: "Question added. Students see it in the lecture's Practice Quiz." });
      setQuizText("");
      setQuizOptions(["", "", "", ""]);
      setQuizCorrect(0);
      setQuizExplanation("");
    } catch (err) {
      setQuizMsg({ ok: false, text: (err as Error).message });
    } finally {
      setQuizBusy(false);
    }
  }

  function removeReference(id: number) {
    setReferences((prev) => prev.filter((r) => r.id !== id));
  }

  const count = lectures.length;

  return (
    <div className="teacher-page">
      <div className="dash-head">
        <span className="dash-eyebrow">Teacher view · {course.description}</span>
        <h1 className="dash-title">{course.title}</h1>
        <p className="dash-meta">
          {course.instructor} · {count} {count === 1 ? "lecture" : "lectures"}
        </p>
      </div>

      <div className="teacher-layout">
        <div className="teacher-main">
          <PiControlPanel />

          <div className="teacher-panel">
            <h3>Your lectures</h3>
            {count === 0 && <p className="empty-note">No lectures yet.</p>}
            {lectures.map((lecture) => (
              <div key={lecture.id} className="teacher-row">
                <div className="teacher-row-info">
                  <span className="teacher-row-title">{lecture.title}</span>
                  <span className="teacher-row-badges">
                    {lecture.isLive && (
                      <span className="badge live">
                        <span className="live-dot" />
                        Live
                      </span>
                    )}
                    {lecture.completed && <span className="badge done">Completed</span>}
                    <span className="badge">
                      {lecture.published ? "Visible to students" : "Hidden"}
                    </span>
                  </span>
                </div>

                {aiMsg?.id === lecture.id && (
                  <p className={aiMsg.ok ? "teacher-notice row-msg" : "teacher-error row-msg"}>{aiMsg.text}</p>
                )}
                {confirmDeleteId === lecture.id ? (
                  <div className="teacher-row-actions">
                    <span className="confirm-text">Delete this lecture?</span>
                    <button
                      className="teacher-btn solid-danger"
                      onClick={() => handleDelete(lecture.id)}
                    >
                      Delete
                    </button>
                    <button
                      className="teacher-btn"
                      onClick={() => setConfirmDeleteId(null)}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="teacher-row-actions">
                    <button
                      className="teacher-btn"
                      onClick={() => togglePublished(lecture.id)}
                    >
                      {lecture.published ? "Hide" : "Show"}
                    </button>
                    {lecture.backendId ? (
                      <>
                        <button
                          className="teacher-btn ai"
                          onClick={() => runAI(lecture, "summary")}
                          disabled={aiBusy !== null}
                          title="Have the AI write the summary from the transcript"
                        >
                          {aiBusy?.id === lecture.id && aiBusy.kind === "summary" ? "Writing..." : "AI summary"}
                        </button>
                        <button
                          className="teacher-btn ai"
                          onClick={() => runAI(lecture, "quiz")}
                          disabled={aiBusy !== null}
                          title="Have the AI write practice questions from the lecture"
                        >
                          {aiBusy?.id === lecture.id && aiBusy.kind === "quiz" ? "Writing..." : "AI quiz"}
                        </button>
                      </>
                    ) : (
                      <button
                        className="teacher-btn"
                        onClick={() => toggleLive(lecture.id)}
                      >
                        {lecture.isLive ? "End live" : "Go live"}
                      </button>
                    )}
                    <button
                      className="teacher-btn danger"
                      onClick={() => setConfirmDeleteId(lecture.id)}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="teacher-panel">
            <h3>Add a lecture</h3>
            <div className="role-switch form-source" role="radiogroup" aria-label="Video source">
              <button
                role="radio"
                aria-checked={source === "camera"}
                className={source === "camera" ? "active" : ""}
                onClick={() => {
                  setSource("camera");
                  setError("");
                }}
              >
                Classroom camera
              </button>
              <button
                role="radio"
                aria-checked={source === "youtube"}
                className={source === "youtube" ? "active" : ""}
                onClick={() => {
                  setSource("youtube");
                  setError("");
                }}
              >
                YouTube link
              </button>
            </div>

            {source === "camera" ? (
              <>
                <p className="form-note">
                  Starts recording on the classroom camera. Students watch it live
                  with sound, and the transcript and recording are added
                  automatically.
                </p>
                <div className="form-grid">
                  <label className="field full">
                    <span>Title</span>
                    <input
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && !busy && handleStartCamera()}
                      placeholder="e.g. Week 4: Logic Gates"
                    />
                  </label>
                </div>
              </>
            ) : (
              <>
                <div className="form-grid">
                  <label className="field">
                    <span>Title</span>
                    <input
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="e.g. Week 4: Logic Gates"
                    />
                  </label>
                  <label className="field">
                    <span>YouTube link</span>
                    <input
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="Video or livestream link"
                    />
                  </label>
                  <label className="field full">
                    <span>Transcript (optional, one line per sentence)</span>
                    <textarea
                      value={transcriptText}
                      onChange={(e) => setTranscriptText(e.target.value)}
                      placeholder={
                        "00:05 Today we're covering binary numbers.\n00:20 Each digit is a bit."
                      }
                    />
                  </label>
                </div>
                <div className="form-checks">
                  <label className="teacher-check">
                    <input
                      type="checkbox"
                      checked={isLive}
                      onChange={(e) => setIsLive(e.target.checked)}
                    />
                    This is a livestream
                  </label>
                  <label className="teacher-check">
                    <input
                      type="checkbox"
                      checked={published}
                      onChange={(e) => setPublished(e.target.checked)}
                    />
                    Visible to students
                  </label>
                </div>
              </>
            )}

            {error && <p className="teacher-error">{error}</p>}
            {notice && <p className="teacher-notice">{notice}</p>}
            {source === "camera" ? (
              <button
                className="teacher-btn primary"
                onClick={handleStartCamera}
                disabled={busy}
              >
                {busy ? "Starting..." : "Start live lecture"}
              </button>
            ) : (
              <button className="teacher-btn primary" onClick={handleAdd} disabled={busy}>
                {busy ? "Building lecture..." : "Add lecture"}
              </button>
            )}
          </div>
        </div>

        <aside className="teacher-side">
          <div className="teacher-panel">
            <h3>Practice questions</h3>
            {quizLectures.length === 0 ? (
              <p className="empty-note">Questions can be added once a lecture has been recorded.</p>
            ) : (
              <>
                <label className="field">
                  <span>Lecture</span>
                  <select
                    value={quizLecture || quizLectures[0].backendId}
                    onChange={(e) => setQuizLecture(e.target.value)}
                  >
                    {quizLectures.map((l) => (
                      <option key={l.id} value={l.backendId}>
                        {l.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Question</span>
                  <input
                    value={quizText}
                    onChange={(e) => setQuizText(e.target.value)}
                    placeholder="e.g. What does F = ma stand for?"
                  />
                </label>
                <div className="field">
                  <span>Answers (pick the correct one)</span>
                  {quizOptions.map((opt, i) => (
                    <div key={i} className="quiz-option-row">
                      <input
                        type="radio"
                        name="quiz-correct"
                        checked={quizCorrect === i}
                        onChange={() => setQuizCorrect(i)}
                        aria-label={`Answer ${i + 1} is correct`}
                      />
                      <input
                        value={opt}
                        onChange={(e) =>
                          setQuizOptions((prev) => prev.map((o, j) => (j === i ? e.target.value : o)))
                        }
                        placeholder={`Answer ${i + 1}${i >= 2 ? " (optional)" : ""}`}
                      />
                    </div>
                  ))}
                </div>
                <label className="field">
                  <span>Explanation (shown after answering, optional)</span>
                  <input
                    value={quizExplanation}
                    onChange={(e) => setQuizExplanation(e.target.value)}
                  />
                </label>
                {quizMsg && (
                  <p className={quizMsg.ok ? "teacher-notice" : "teacher-error"}>{quizMsg.text}</p>
                )}
                <button
                  className="teacher-btn primary"
                  onClick={handleAddQuestion}
                  disabled={quizBusy}
                >
                  {quizBusy ? "Adding..." : "Add question"}
                </button>
              </>
            )}
          </div>

          <CourseSettingsPanel settings={settings} onChange={setSettings} />

          <div className="teacher-panel">
            <h3>Reference material</h3>
            {references.length === 0 && <p className="empty-note">Nothing uploaded yet.</p>}
            {references.map((ref) => (
              <div key={ref.id} className="teacher-row">
                <div className="teacher-row-info">
                  <span className="teacher-row-title">{ref.title}</span>
                  <span className="teacher-row-badges">
                    <span className="badge">{ref.type}</span>
                    {ref.backendId !== undefined && (
                      <span className="badge done">AI can cite this</span>
                    )}
                  </span>
                </div>
                {ref.backendId === undefined && (
                  <div className="teacher-row-actions">
                    <button
                      className="teacher-btn danger"
                      onClick={() => removeReference(ref.id)}
                    >
                      Remove
                    </button>
                  </div>
                )}
              </div>
            ))}
            {uploadMsg && (
              <p className={uploadMsg.ok ? "teacher-notice" : "teacher-error"}>{uploadMsg.text}</p>
            )}
            <label className={uploading ? "teacher-btn upload-btn disabled" : "teacher-btn upload-btn"}>
              {uploading ? "Uploading..." : "Upload material (PDF, PowerPoint, text)"}
              <input
                type="file"
                accept=".pdf,.pptx,.txt"
                onChange={handleTextbook}
                disabled={uploading}
                hidden
              />
            </label>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default TeacherDashboard;