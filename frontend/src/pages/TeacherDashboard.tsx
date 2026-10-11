import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type {
  Course,
  Lecture,
  ReferenceMaterial,
  CourseSettings,
} from "../data/mockData";
import { parseTranscript, generateFromTranscript } from "../api";
import CourseSettingsPanel from "../components/CourseSettingsPanel";

interface TeacherDashboardProps {
  course: Course;
  lectures: Lecture[];
  setLectures: Dispatch<SetStateAction<Lecture[]>>;
  references: ReferenceMaterial[];
  setReferences: Dispatch<SetStateAction<ReferenceMaterial[]>>;
  settings: CourseSettings;
  setSettings: Dispatch<SetStateAction<CourseSettings>>;
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
}: TeacherDashboardProps) {
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [transcriptText, setTranscriptText] = useState("");
  const [isLive, setIsLive] = useState(false);
  const [published, setPublished] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // TODO (backend teammate): also POST the new lecture to the server
  // (teacher role only), e.g. POST /api/lectures
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
    setBusy(true);

    const transcript = parseTranscript(transcriptText);
    const generated =
      transcript.length > 0
        ? await generateFromTranscript(transcript)
        : { liveSummary: [], quiz: [] };

    const newLecture: Lecture = {
      id: Date.now(),
      courseId: course.id,
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
  }

  // TODO (backend teammate): also send the file to the server (teacher role only),
  // e.g. POST /api/textbook
  function handleTextbook(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setReferences((prev) => [
      ...prev,
      {
        id: Date.now(),
        courseId: course.id,
        title: file.name,
        type: "textbook",
        source: "Uploaded by teacher",
      },
    ]);
    e.target.value = "";
  }

  function removeReference(id: number) {
    setReferences((prev) => prev.filter((r) => r.id !== id));
  }

  return (
    <div className="teacher-page">
      <h1>Teacher: {course.title}</h1>

      <CourseSettingsPanel settings={settings} onChange={setSettings} />

      <div className="teacher-panel">
        <h3>Add a lecture</h3>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Lecture title"
        />
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="YouTube link (video or livestream)"
        />
        <textarea
          value={transcriptText}
          onChange={(e) => setTranscriptText(e.target.value)}
          placeholder={
            "Optional: paste a transcript to build the lecture from it, one line per sentence.\nExample:\n00:05 Today we're covering binary numbers.\n00:20 Each digit is a bit."
          }
        />
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
        {error && <p className="teacher-error">{error}</p>}
        <button className="teacher-btn primary" onClick={handleAdd} disabled={busy}>
          {busy ? "Building lecture..." : "Add lecture"}
        </button>
      </div>

      <div className="teacher-panel">
        <h3>Your lectures</h3>
        {lectures.length === 0 && <p>No lectures yet.</p>}
        {lectures.map((lecture) => (
          <div key={lecture.id} className="teacher-row">
            <div className="teacher-row-title">
              {lecture.title}
              {lecture.isLive && <span className="live-badge">LIVE</span>}
              {!lecture.published && <span className="hidden-badge">HIDDEN</span>}
            </div>
            <button
              className="teacher-btn"
              onClick={() => togglePublished(lecture.id)}
            >
              {lecture.published ? "Hide from students" : "Show to students"}
            </button>
            <button className="teacher-btn" onClick={() => toggleLive(lecture.id)}>
              {lecture.isLive ? "End livestream" : "Go live"}
            </button>
            <button
              className="teacher-btn danger"
              onClick={() => handleDelete(lecture.id)}
            >
              Delete
            </button>
          </div>
        ))}
      </div>

      <div className="teacher-panel">
        <h3>Textbooks and reference material</h3>
        {references.length === 0 && <p>Nothing uploaded yet.</p>}
        {references.map((ref) => (
          <div key={ref.id} className="teacher-row">
            <div className="teacher-row-title">
              {ref.title}
              <span className="hidden-badge">{ref.type}</span>
            </div>
            <button
              className="teacher-btn danger"
              onClick={() => removeReference(ref.id)}
            >
              Remove
            </button>
          </div>
        ))}
        <label className="teacher-btn">
          Upload textbook
          <input
            type="file"
            accept=".pdf,.txt,.epub"
            onChange={handleTextbook}
            hidden
          />
        </label>
      </div>
    </div>
  );
}

export default TeacherDashboard;