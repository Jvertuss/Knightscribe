/* eslint-disable @typescript-eslint/no-explicit-any */
import type { Lecture, SummaryPoint, TranscriptLine } from "./data/mockData";

const BASE = (import.meta.env.VITE_API_BASE_URL as string).replace(/\/$/, "");

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

export const getCourses = () => get<unknown[]>("/courses");
export const getLecture = (id: string) => get<any>(`/lectures/${id}`);
export const getTimeline = (id: string) => get<any>(`/lectures/${id}/timeline`);
export const searchCourse = (courseId: number, q: string) =>
  get<any>(`/courses/${courseId}/search?q=${encodeURIComponent(q)}`);
export const getCourseSettings = (courseId: number) =>
  get<any>(`/courses/${courseId}/settings`);

// ---- what the backend sends for one lecture ----
interface ApiLecture {
  id: string;
  course_id: number;
  title: string;
  status: string; // recording | processing | completed | error
  live_summary: string | null;
  final_summary: string | null;
  stream_status: string; // offline | starting | live | ended | error
  recording_view_allowed: boolean;
  recording_url: string | null;
  transcript_segments: { start_seconds: number; text: string }[];
}

const fmt = (s: number) =>
  `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function toLecture(d: ApiLecture, index: number): Lecture {
  const isLive = d.status === "recording" || d.stream_status === "live";

  const transcript: TranscriptLine[] = d.transcript_segments.map((s) => ({
    time: fmt(s.start_seconds),
    text: s.text,
  }));

  const summaryText = isLive ? d.live_summary : d.final_summary ?? d.live_summary;
  const liveSummary: SummaryPoint[] = summaryText
    ? summaryText
        .split(/(?<=[.!?])\s+/)
        .filter(Boolean)
        .map((text) => ({ time: "0:00", text }))
    : [];

  // backend decides if the recording may be shown
  const hasRealVideo =
    d.recording_view_allowed &&
    !!d.recording_url &&
    !d.recording_url.includes("example.com");

  return {
    id: 1000 + index,
    backendId: d.id,
    courseId: d.course_id,
    title: d.title,
    videoUrl: hasRealVideo ? (d.recording_url as string) : "",
    isLive,
    published: true,
    completed: d.status === "completed",
    transcript,
    liveSummary,
    quiz: [],
  };
}

export async function loadLectures(courseId: number): Promise<Lecture[]> {
  const list = await get<{ id: string }[]>(`/courses/${courseId}/lectures`);
  const details = await Promise.all(
    list.map((l) => get<ApiLecture>(`/lectures/${l.id}`))
  );
  return details.map(toLecture);
}
