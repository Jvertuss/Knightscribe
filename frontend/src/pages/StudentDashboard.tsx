import { useEffect, useState } from "react";
import { chapters } from "../data/mockData";
import { fetchChapters } from "../backend";
import type {
  Chapter,
  Course,
  Lecture,
  ReferenceMaterial,
  CourseSettings,
} from "../data/mockData";
import LessonCard from "../components/LessonCard";
import VideoPlayer from "../components/VideoPlayer";
import ChapterList from "../components/ChapterList";
import TranscriptPanel from "../components/TranscriptPanel";
import LiveSummaryPanel from "../components/LiveSummaryPanel";
import ChatPanel from "../components/ChatPanel";
import QuizPanel from "../components/QuizPanel";
import ReferencePanel from "../components/ReferencePanel";
import SearchPanel from "../components/SearchPanel";

interface StudentDashboardProps {
  course: Course;
  lectures: Lecture[];
  references: ReferenceMaterial[];
  settings: CourseSettings;
}

function StudentDashboard({
  course,
  lectures,
  references,
  settings,
}: StudentDashboardProps) {
  const [selectedLectureId, setSelectedLectureId] = useState<number | null>(null);
  const [seekTo, setSeekTo] = useState<{ seconds: number } | null>(null);
  const [activeChapterId, setActiveChapterId] = useState<number | null>(null);

  // Until the student picks one, open the live lecture, or else the first one
  const selectedLecture =
    lectures.find((l) => l.id === selectedLectureId) ??
    lectures.find((l) => l.isLive) ??
    lectures[0];

  // Board / slide snapshots: from the backend for real lectures (checked again
  // every 10 s while the lecture is live), the mock ones otherwise
  const [boardChapters, setBoardChapters] = useState<{ lectureId: number; list: Chapter[] } | null>(null);
  const backendId = selectedLecture?.backendId;
  const selectedId = selectedLecture?.id;
  const isLive = selectedLecture?.isLive ?? false;
  useEffect(() => {
    if (!backendId || selectedId === undefined) return;
    let cancelled = false;
    let timer: number | undefined;
    async function load() {
      try {
        const list = await fetchChapters(backendId as string, selectedId as number);
        if (!cancelled) setBoardChapters({ lectureId: selectedId as number, list });
      } catch (err) {
        console.warn("loading board snapshots failed:", err);
      }
      if (!cancelled && isLive) timer = window.setTimeout(load, 10000);
    }
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [backendId, selectedId, isLive]);

  const lectureChapters = !selectedLecture
    ? []
    : selectedLecture.backendId
    ? boardChapters?.lectureId === selectedLecture.id
      ? boardChapters.list
      : []
    : chapters.filter((c) => c.lectureId === selectedLecture.id);

  // search result -> open that lecture at that moment
  function openAt(lectureBackendId: string, seconds: number | null) {
    const target = lectures.find((l) => l.backendId === lectureBackendId);
    if (!target) return false;
    setSelectedLectureId(target.id);
    setActiveChapterId(null);
    setSeekTo(seconds !== null ? { seconds: Math.floor(seconds) } : null);
    // after the lecture opens, bring its video into view
    window.requestAnimationFrame(() =>
      document.querySelector(".session-layout")?.scrollIntoView({ behavior: "smooth" })
    );
    return true;
  }

  // Live streams are always watchable; rewatching depends on the teacher's setting
  const canWatch = selectedLecture
    ? selectedLecture.isLive || settings.allowRecordings
    : false;

  const count = lectures.length;

  return (
    <div className="student-page">
      <div className="dash-head">
        <span className="dash-eyebrow">{course.description}</span>
        <h1 className="dash-title">{course.title}</h1>
        <p className="dash-meta">
          {course.instructor} · {count} {count === 1 ? "lecture" : "lectures"}
        </p>
      </div>

      <SearchPanel courseId={course.id} onOpen={openAt} />

      <h2 className="section-label">Lectures</h2>
      {count === 0 && <p className="empty-note">No lectures are available yet.</p>}
      <div className="lecture-strip">
        {lectures.map((lecture) => (
          <LessonCard
            key={lecture.id}
            lesson={lecture}
            selected={lecture.id === selectedLecture?.id}
            onSelect={() => {
              setSelectedLectureId(lecture.id);
              setSeekTo(null);
              setActiveChapterId(null);
            }}
          />
        ))}
      </div>

      {selectedLecture && (
        <div className="session-layout">
          <div className="session-main">
            {canWatch ? (
              <>
                <VideoPlayer
                  key={selectedLecture.id}
                  title={selectedLecture.title}
                  videoUrl={selectedLecture.videoUrl}
                  seekTo={seekTo}
                />
                <ChapterList
                  chapters={lectureChapters}
                  activeId={activeChapterId}
                  onSelect={(chapter) => {
                    setActiveChapterId(chapter.id);
                    setSeekTo({ seconds: chapter.startSeconds });
                  }}
                />
              </>
            ) : (
              <div className="recording-locked">
                <h3>{selectedLecture.title}</h3>
                <p>
                  This recording isn't available. Your teacher has turned off
                  recordings for this course.
                </p>
              </div>
            )}
            <TranscriptPanel
              lines={selectedLecture.transcript}
              isLive={selectedLecture.isLive}
            />
          </div>

          <div className="session-side">
            <LiveSummaryPanel
              key={`summary-${selectedLecture.id}`}
              points={selectedLecture.liveSummary}
              isLive={selectedLecture.isLive}
              onSeek={(seconds) => {
                setActiveChapterId(null);
                setSeekTo({ seconds });
              }}
            />
            <ChatPanel
              key={selectedLecture.id}
              lecture={selectedLecture}
              settings={settings}
              onSeek={(seconds) => {
                setActiveChapterId(null);
                setSeekTo({ seconds });
              }}
            />
            {settings.allowPracticeQuestions && (
              <QuizPanel key={`quiz-${selectedLecture.id}`} lecture={selectedLecture} />
            )}
            <ReferencePanel
              key={`ref-${selectedLecture.id}`}
              references={references}
              courseId={selectedLecture.courseId}
              lectureId={selectedLecture.id}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default StudentDashboard;
