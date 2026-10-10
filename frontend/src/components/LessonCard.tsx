import type { Lesson } from "../data/mockData";

interface LessonCardProps {
  lesson: Lesson;
  selected: boolean;
  onSelect: () => void;
}

function LessonCard({ lesson, selected, onSelect }: LessonCardProps) {
  return (
    <div
      className={selected ? "lesson-card selected" : "lesson-card"}
      onClick={onSelect}
    >
      <h2>
         {lesson.title}
         {lesson.isLive && <span className="live-badge">LIVE</span>}
      </h2>
      <p>{lesson.completed ? "Completed" : "Not started"}</p>
    </div>
  );
}

export default LessonCard;