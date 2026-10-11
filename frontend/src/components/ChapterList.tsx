import { useState } from "react";
import type { Chapter } from "../data/mockData";

interface ChapterListProps {
  chapters: Chapter[];
  activeId: number | null;
  onSelect: (chapter: Chapter) => void; // jump the video to this snapshot's moment
  canSeek?: boolean; // false while live (the camera stream can't jump)
}

function formatTime(total: number) {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

// The cleaned copy may not exist yet (it's saved a moment after the photo):
// fall back to the original photo once, then hide the picture.
function fallBack(e: React.SyntheticEvent<HTMLImageElement>, original?: string) {
  const img = e.currentTarget;
  if (original && img.src !== original) img.src = original;
  else img.hidden = true;
}

// Board / slide snapshots from the classroom camera, in time order.
// Clicking one opens it large, with its details and a jump to that moment.
function ChapterList({ chapters, activeId, onSelect, canSeek = true }: ChapterListProps) {
  const [openId, setOpenId] = useState<number | null>(null);
  const [showOriginal, setShowOriginal] = useState(false);

  if (chapters.length === 0) {
    return (
      <div className="chapter-list">
        <h3>Board &amp; slides</h3>
        <p className="empty-note">
          Photos of the board and slides appear here during the lecture.
        </p>
      </div>
    );
  }

  const index = chapters.findIndex((c) => c.id === openId);
  const open = index >= 0 ? chapters[index] : null;

  function openAt(i: number) {
    setOpenId(chapters[i].id);
    setShowOriginal(false);
  }

  return (
    <div className="chapter-list">
      <h3>Board &amp; slides</h3>

      <div className="chapter-strip">
        {chapters.map((chapter, i) => (
          <button
            key={chapter.id}
            className={
              chapter.id === openId || chapter.id === activeId
                ? "chapter-card active"
                : "chapter-card"
            }
            onClick={() => (chapter.id === openId ? setOpenId(null) : openAt(i))}
            aria-expanded={chapter.id === openId}
            title="Show this snapshot"
          >
            <img
              src={chapter.snapshotUrl}
              alt={`${chapter.title} at ${formatTime(chapter.startSeconds)}`}
              onError={(e) => fallBack(e, chapter.originalUrl)}
            />
            <div className="chapter-time">{formatTime(chapter.startSeconds)}</div>
            <div className="chapter-title">{chapter.title}</div>
          </button>
        ))}
      </div>

      {open && (
        <div className="snapshot-detail">
          <div className="snapshot-head">
            <div>
              <strong>
                {open.title} · {formatTime(open.startSeconds)}
              </strong>
              <span className="snapshot-meta">
                Snapshot {index + 1} of {chapters.length} ·{" "}
                {open.kind === "slide"
                  ? "slide on the projector"
                  : showOriginal && open.originalUrl
                  ? "original photo"
                  : "cleaned copy (white background, saturated marker)"}
              </span>
            </div>
            <button className="snapshot-close" onClick={() => setOpenId(null)} aria-label="Close snapshot">
              ×
            </button>
          </div>

          <img
            key={`${open.id}-${showOriginal}`}
            className="snapshot-large"
            src={showOriginal && open.originalUrl ? open.originalUrl : open.snapshotUrl}
            alt={`${open.title} at ${formatTime(open.startSeconds)}`}
            onError={(e) => fallBack(e, open.originalUrl)}
          />

          <div className="snapshot-actions">
            <button
              className="teacher-btn primary"
              onClick={() => onSelect(open)}
              disabled={!canSeek}
              title={canSeek ? "Play the recording from this moment" : "Available once the lecture's recording is ready"}
            >
              ▶ Jump to {formatTime(open.startSeconds)}
            </button>
            {!canSeek && <span className="snapshot-meta">Jumping works once the recording is ready.</span>}
            {open.originalUrl && (
              <button className="teacher-btn" onClick={() => setShowOriginal((v) => !v)}>
                {showOriginal ? "Show cleaned copy" : "Show original photo"}
              </button>
            )}
            <span className="snapshot-nav">
              <button
                className="teacher-btn"
                onClick={() => openAt(index - 1)}
                disabled={index === 0}
                aria-label="Previous snapshot"
              >
                ←
              </button>
              <button
                className="teacher-btn"
                onClick={() => openAt(index + 1)}
                disabled={index === chapters.length - 1}
                aria-label="Next snapshot"
              >
                →
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default ChapterList;
