import type { Chapter } from "../data/mockData";

interface ChapterListProps {
  chapters: Chapter[];
  activeId: number | null;
  onSelect: (chapter: Chapter) => void;
}

function formatTime(total: number) {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function ChapterList({ chapters, activeId, onSelect }: ChapterListProps) {
  if (chapters.length === 0) {
    return (
      <div className="chapter-list">
        <h3>Chapters</h3>
        <p>No chapters yet.</p>
      </div>
    );
  }

  return (
    <div className="chapter-list">
      <h3>Chapters</h3>
      <div className="chapter-strip">
        {chapters.map((chapter) => (
          <button
            key={chapter.id}
            className={
              chapter.id === activeId ? "chapter-card active" : "chapter-card"
            }
            onClick={() => onSelect(chapter)}
          >
            <img src={chapter.snapshotUrl} alt={chapter.title} />
            <div className="chapter-time">{formatTime(chapter.startSeconds)}</div>
            <div className="chapter-title">{chapter.title}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

export default ChapterList;