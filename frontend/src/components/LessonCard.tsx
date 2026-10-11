import type { Lesson } from "../data/mockData";

interface LessonCardProps {
  lesson: Lesson;
  selected: boolean;
  onSelect: () => void;
}

function LessonCard({ lesson, selected, onSelect }: LessonCardProps) {
  const lines = lesson.transcript.length;

  return (
    <button
      className={selected ? "lesson-card selected" : "lesson-card"}
      aria-pressed={selected}
      onClick={onSelect}
    >
      {lesson.isLive ? (
        <span className="lesson-status live">
          <span className="live-dot" />
          Live now
        </span>
      ) : (
        <span className={lesson.completed ? "lesson-status done" : "lesson-status"}>
          {lesson.completed ? "Completed" : "Recorded"}
        </span>
      )}
      <span className="lesson-title">{lesson.title}</span>
      <span className="lesson-meta">
        {lines === 0
          ? "No transcript yet"
          : `${lines} transcript ${lines === 1 ? "line" : "lines"}`}
      </span>
    </button>
  );
}

export default LessonCard;
