import {
  courses as mockCourses,
  lectures as mockLectures,
  defaultSettings,
} from "./data/mockData";
import type {
  Chapter,
  ChatSource,
  Course,
  CourseSettings,
  Lecture,
  QuizQuestion,
  ReferenceMaterial,
  SummaryPoint,
  TranscriptLine,
} from "./data/mockData";

// Missing env vars must not crash the app: every request just fails and
// the loaders below fall back to the mock data.
const BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "")
  .trim()
  .replace(/\/$/, "");

// The AI features (chat, AI summary, AI quiz) can use a different backend,
// e.g. one running on this laptop with its own Gemini key. Empty = same as BASE.
const AI_BASE =
  ((import.meta.env.VITE_AI_BASE_URL as string | undefined) ?? "").trim().replace(/\/$/, "") || BASE;

// Pi camera (MJPEG), e.g. http://knightcribe.local:5000/video.
// Only used for a lecture that is live right now.
const PI_STREAM_URL = (
  (import.meta.env.VITE_PI_STREAM_URL as string | undefined) ?? ""
).trim();

async function get<T>(path: string): Promise<T> {
  if (!BASE) throw new Error("VITE_API_BASE_URL is not set");
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  if (!BASE) throw new Error("VITE_API_BASE_URL is not set");
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

// Sends JSON or form data; on failure throws the backend's own explanation.
async function send<T>(
  method: "POST" | "PUT",
  path: string,
  body: unknown,
  base: string = BASE
): Promise<T> {
  if (!base) throw new Error("The backend isn't configured (VITE_API_BASE_URL is not set).");
  let res: Response;
  try {
    res =
      body instanceof FormData
        ? await fetch(`${base}${path}`, { method, body })
        : await fetch(`${base}${path}`, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
  } catch {
    throw new Error("Can't reach the server. Check your internet connection and try again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "";
    throw new Error(detail || `The server answered with error ${res.status}.`);
  }
  return data as T;
}

// ---- courses ----
interface ApiCourse {
  id: number;
  name: string;
  code: string | null;
  professor_name: string | null;
}

export async function loadCourses(): Promise<Course[]> {
  try {
    const list = await get<ApiCourse[]>("/courses");
    if (list.length === 0) return mockCourses;
    return list.map((c) => ({
      id: c.id,
      title: c.name,
      instructor: c.professor_name ?? "",
      description: c.code ?? "",
    }));
  } catch (err) {
    console.warn("loadCourses failed, using mock courses:", err);
    return mockCourses;
  }
}

// ---- what the backend sends for one lecture ----
interface ApiLecture {
  id: string;
  course_id: number;
  title: string;
  status: string; // recording | processing | completed | error
  live_summary: string | null;
  final_summary: string | null;
  stream_status: string; // offline | starting | live | ended | error
  stream_protocol: string | null;
  live_stream_url: string | null;
  recording_view_allowed: boolean;
  recording_url: string | null; // null when the teacher turned recordings off
  transcript_segments: { start_seconds: number; text: string }[];
}

const fmt = (s: number) =>
  `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// The frontend uses number ids, the backend uses strings like
// "lecture_2026-10-10_11-30-00". Each backend id gets its own number the
// first time we see it and keeps it, so reloading never changes which
// lecture is selected. Starts at 1000 so it can't clash with the mock ids.
const lectureIds = new Map<string, number>();
function stableId(backendId: string): number {
  let id = lectureIds.get(backendId);
  if (id === undefined) {
    id = 1000 + lectureIds.size;
    lectureIds.set(backendId, id);
  }
  return id;
}

const isLiveNow = (d: ApiLecture) => d.stream_status === "live";

// "mjpeg:" tells VideoPlayer to show the stream in an <img> tag.
function videoUrlFor(d: ApiLecture, isLive: boolean): string {
  if (isLive) {
    if (d.live_stream_url) {
      const mjpeg = !d.stream_protocol || d.stream_protocol === "mjpeg";
      return mjpeg ? `mjpeg:${d.live_stream_url}` : d.live_stream_url;
    }
    return PI_STREAM_URL ? `mjpeg:${PI_STREAM_URL}` : "";
  }
  // Finished lectures only ever show the saved recording, never the camera.
  const hasRecording =
    !!d.recording_url && !d.recording_url.includes("example.com");
  return hasRecording ? (d.recording_url as string) : "";
}

// The AI stores summaries as JSON: [{"seconds": 75, "text": "..."}]. Older ones
// are plain text: those become one point per sentence, without a time.
function parseSummary(text: string | null): SummaryPoint[] {
  if (!text) return [];
  try {
    const points = JSON.parse(text);
    if (Array.isArray(points)) {
      return points
        .filter((p) => p && typeof p.text === "string")
        .map((p) => ({
          time: typeof p.seconds === "number" ? fmt(p.seconds) : "",
          text: p.text,
        }));
    }
  } catch {
    // not JSON: plain text
  }
  return text
    .split(/(?<=[.!?])\s+/)
    .filter(Boolean)
    .map((t) => ({ time: "", text: t }));
}

function toLecture(d: ApiLecture): Lecture {
  const isLive = isLiveNow(d);

  const transcript: TranscriptLine[] = d.transcript_segments.map((s) => ({
    time: fmt(s.start_seconds),
    text: s.text,
  }));

  const summaryText = isLive ? d.live_summary : d.final_summary ?? d.live_summary;
  const liveSummary = parseSummary(summaryText);

  return {
    id: stableId(d.id),
    backendId: d.id,
    courseId: d.course_id,
    title: d.title,
    videoUrl: videoUrlFor(d, isLive),
    isLive,
    published: true,
    completed: d.status === "completed",
    transcript,
    liveSummary,
    quiz: [],
  };
}

// The backend's lectures for a course. Throws if the backend can't be reached,
// so a refresh can keep what is on screen instead of switching to mock data.
export async function fetchLectures(courseId: number): Promise<Lecture[]> {
  const list = await get<{ id: string }[]>(`/courses/${courseId}/lectures`);
  // one broken lecture shouldn't hide all the others
  const results = await Promise.allSettled(
    list.map((l) => get<ApiLecture>(`/lectures/${l.id}`))
  );
  return results
    .filter((r) => r.status === "fulfilled")
    .map((r) => toLecture((r as PromiseFulfilledResult<ApiLecture>).value));
}

// First load: falls back to the mock lectures if the backend is down or empty.
export async function loadLectures(courseId: number): Promise<Lecture[]> {
  const mock = mockLectures.filter((l) => l.courseId === courseId);
  try {
    const real = await fetchLectures(courseId);
    return real.length > 0 ? real : mock;
  } catch (err) {
    console.warn(`loadLectures(${courseId}) failed, using mock lectures:`, err);
    return mock;
  }
}

// ---- course settings (backend uses snake_case names) ----
interface ApiSettings {
  ai_enabled: boolean;
  hints_allowed: boolean;
  explanations_allowed: boolean;
  final_answers_allowed: boolean;
  practice_questions_allowed: boolean;
  recording_view_allowed: boolean;
}

const fromApiSettings = (d: ApiSettings): CourseSettings => ({
  aiHelpEnabled: d.ai_enabled,
  allowHints: d.hints_allowed,
  allowExplanations: d.explanations_allowed,
  allowFinalAnswers: d.final_answers_allowed,
  allowPracticeQuestions: d.practice_questions_allowed,
  allowRecordings: d.recording_view_allowed,
});

const toApiSettings = (s: CourseSettings): ApiSettings => ({
  ai_enabled: s.aiHelpEnabled,
  hints_allowed: s.allowHints,
  explanations_allowed: s.allowExplanations,
  final_answers_allowed: s.allowFinalAnswers,
  practice_questions_allowed: s.allowPracticeQuestions,
  recording_view_allowed: s.allowRecordings,
});

export async function loadSettings(courseId: number): Promise<CourseSettings> {
  try {
    return fromApiSettings(
      await get<ApiSettings>(`/courses/${courseId}/settings`)
    );
  } catch (err) {
    console.warn(`loadSettings(${courseId}) failed, using defaults:`, err);
    return defaultSettings;
  }
}

// Throws on failure, so the caller can undo the change on screen.
export async function saveSettings(
  courseId: number,
  s: CourseSettings
): Promise<CourseSettings> {
  const saved = await put<ApiSettings>(
    `/courses/${courseId}/settings`,
    toApiSettings(s)
  );
  return fromApiSettings(saved);
}

// ---- the AI chatbot (answers only from this course's material) ----
interface ApiSource {
  source_id: string;
  source_type: "document" | "transcript" | "board_event";
  title: string;
  source_location: string | null;
  lecture_id: string | null;
  timestamp_seconds: number | null;
}

export async function askAI(
  courseId: number,
  lectureId: string | undefined,
  message: string,
  mode: "ask" | "hint" | "explain" | "answer"
): Promise<{ answer: string; sources: ChatSource[] }> {
  if (!AI_BASE) throw new Error("The AI isn't available (VITE_API_BASE_URL is not set).");
  let res: Response;
  try {
    res = await fetch(`${AI_BASE}/courses/${courseId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, mode, lecture_id: lectureId ?? null }),
    });
  } catch {
    throw new Error("Can't reach the AI right now. Check your internet connection and try again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // the backend explains refusals in plain words (e.g. "hints are turned off")
    const detail = typeof data.detail === "string" ? data.detail : "";
    throw new Error(detail || `The AI couldn't answer (error ${res.status}). Try again.`);
  }
  return {
    answer: data.answer,
    sources: (data.sources as ApiSource[]).map((s) => ({
      sourceId: s.source_id,
      type: s.source_type,
      title: s.title,
      location: s.source_location,
      lectureId: s.lecture_id,
      seconds: s.timestamp_seconds,
    })),
  };
}

// ---- reference documents (PDF / PowerPoint / text the professor uploads) ----
interface ApiDocument {
  id: number;
  course_id: number;
  title: string;
  document_type: string; // pdf | powerpoint | text
  original_filename: string | null;
  processing_status: string;
}

const DOC_TYPE: Record<string, ReferenceMaterial["type"]> = {
  pdf: "textbook",
  powerpoint: "slides",
  text: "article",
};

const toReference = (d: ApiDocument): ReferenceMaterial => ({
  id: 1_000_000 + d.id, // can't clash with mock or teacher-added ids
  backendId: d.id,
  courseId: d.course_id,
  title: d.title,
  type: DOC_TYPE[d.document_type] ?? "article",
  source: d.original_filename ? `Uploaded: ${d.original_filename}` : "Uploaded by the professor",
});

// Throws if the backend can't be reached, so the caller can keep what it has.
export async function fetchDocuments(courseId: number): Promise<ReferenceMaterial[]> {
  const list = await get<ApiDocument[]>(`/courses/${courseId}/documents`);
  return list.filter((d) => d.processing_status === "ready").map(toReference);
}

export async function uploadDocument(courseId: number, file: File): Promise<ReferenceMaterial> {
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name.replace(/\.[^.]+$/, ""));
  return toReference(await send<ApiDocument>("POST", `/courses/${courseId}/documents/upload`, form));
}

// ---- practice quiz ----
interface ApiQuizQuestion {
  id: number;
  question: string;
  options: string[];
}

export interface QuizResult {
  correct: boolean;
  correctOption: number;
  explanation: string | null;
}

// [] when the lecture has no questions, or the professor turned quizzes off (403)
export async function fetchQuiz(lectureId: string): Promise<QuizQuestion[]> {
  try {
    const list = await get<ApiQuizQuestion[]>(`/lectures/${lectureId}/quiz-questions`);
    return list.map((q) => ({
      id: q.id,
      backendId: q.id,
      question: q.question,
      choices: q.options,
      answerIndex: -1,
    }));
  } catch (err) {
    console.warn("fetchQuiz failed:", err);
    return [];
  }
}

export async function answerQuiz(questionId: number, selected: number): Promise<QuizResult> {
  const r = await send<{ correct: boolean; correct_option: number; explanation: string | null }>(
    "POST",
    `/quiz-questions/${questionId}/answer`,
    { selected_option: selected }
  );
  return { correct: r.correct, correctOption: r.correct_option, explanation: r.explanation };
}

export async function createQuizQuestion(
  lectureId: string,
  q: { question: string; options: string[]; correctOption: number; explanation: string }
): Promise<void> {
  await send("POST", `/lectures/${lectureId}/quiz-questions`, {
    question: q.question,
    options: q.options,
    correct_option: q.correctOption,
    explanation: q.explanation || null,
  });
}

// ---- board / slide snapshots, shown as photo chapters ----
// Only the photos are used: the Pi's OCR misreads the board, so its text is ignored.
interface ApiBoardEvent {
  id: number;
  timestamp_seconds: number;
  image_url: string | null;
  event_type: string | null;
}

export async function fetchChapters(lectureId: string, frontendLectureId: number): Promise<Chapter[]> {
  const list = await get<ApiBoardEvent[]>(`/lectures/${lectureId}/board-events`);
  return list
    .filter((e) => e.image_url)
    .map((e) => ({
      id: e.id,
      lectureId: frontendLectureId,
      startSeconds: Math.floor(e.timestamp_seconds),
      title: e.event_type === "slide" ? "Slide" : "Board",
      snapshotUrl: e.image_url as string,
    }));
}

// ---- search across the course ----
export interface SearchResult {
  type: "document" | "transcript" | "whiteboard";
  title: string;
  content: string;
  lectureId: string | null; // backend lecture id
  seconds: number | null;
  location: string | null;
}

export async function searchCourse(courseId: number, q: string): Promise<SearchResult[]> {
  const data = await get<{
    results: {
      source_type: SearchResult["type"];
      title: string;
      content: string;
      lecture_id: string | null;
      timestamp_seconds: number | null;
      source_location: string | null;
    }[];
  }>(`/courses/${courseId}/search?q=${encodeURIComponent(q)}&max_results=12`);
  return data.results
    .filter((r) => r.source_type !== "whiteboard") // OCR text from the board: not reliable
    .map((r) => ({
    type: r.source_type,
    title: r.title,
    content: r.content,
    lectureId: r.lecture_id,
    seconds: r.timestamp_seconds,
    location: r.source_location,
  }));
}

// ---- AI-written summary and practice questions (Gemini, on the backend) ----
export async function generateSummary(lectureId: string, final: boolean): Promise<number> {
  const r = await send<{ points: unknown[] }>(
    "POST",
    `/lectures/${lectureId}/summary/generate${final ? "?final=true" : ""}`,
    {},
    AI_BASE
  );
  return r.points.length;
}

export async function generateQuiz(lectureId: string, count = 4): Promise<number> {
  const r = await send<{ added: number }>(
    "POST",
    `/lectures/${lectureId}/quiz/generate?count=${count}`,
    {},
    AI_BASE
  );
  return r.added;
}
