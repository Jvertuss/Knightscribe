import { useState } from "react";
import { chapters } from "../data/mockData";
import type {
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

  const selectedLecture = lectures.find((l) => l.id === selectedLectureId);
  const lectureChapters = chapters.filter(
    (c) => c.lectureId === selectedLectureId
  );

  // Live streams are always watchable; rewatching depends on the teacher's setting
  const canWatch = selectedLecture
    ? selectedLecture.isLive || settings.allowRecordings
    : false;

  return (
    <div>
      <h1>{course.title}</h1>
      <p className="course-description">
        {course.instructor} · {course.description}
      </p>

      <h2>Lectures</h2>
      {lectures.length === 0 && <p>No lectures are available yet.</p>}
      {lectures.map((lecture) => (
        <LessonCard
          key={lecture.id}
          lesson={lecture}
          selected={lecture.id === selectedLectureId}
          onSelect={() => {
            setSelectedLectureId(lecture.id);
            setSeekTo(null);
            setActiveChapterId(null);
          }}
        />
      ))}

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
            <TranscriptPanel lines={selectedLecture.transcript} />
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
            />
            {settings.allowPracticeQuestions && (
              <QuizPanel
                key={`quiz-${selectedLecture.id}`}
                questions={selectedLecture.quiz}
              />
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