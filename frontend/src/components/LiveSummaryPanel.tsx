import type { SummaryPoint } from "../data/mockData";

interface LiveSummaryPanelProps {
  points: SummaryPoint[];
  isLive: boolean;
  onSeek?: (seconds: number) => void;
}

// "1:30" -> 90 ("" when the point has no time)
function toSeconds(time: string): number | null {
  const [minutes, seconds] = time.split(":").map(Number);
  return Number.isFinite(minutes) && Number.isFinite(seconds) ? minutes * 60 + seconds : null;
}

// The AI's notes for the lecture: rewritten every minute while it is live,
// and a final version once it has ended. Each point jumps to when it was said.
function LiveSummaryPanel({ points, isLive, onSeek }: LiveSummaryPanelProps) {
  // newest first while live, so the latest topic is on top
  const shown = isLive ? [...points].reverse() : points;

  return (
    <div className="summary-panel">
      <div className="summary-header">
        <h3>{isLive ? "Live Summary" : "Summary"}</h3>
        {isLive && <span className="live-badge">LIVE</span>}
      </div>
      {isLive && points.length > 0 && (
        <p className="summary-note">Written by AI from the lecture, updated every minute.</p>
      )}

      {shown.length === 0 && (
        <p className="empty-note">
          {isLive
            ? "The AI summary appears about a minute into the lecture."
            : "No summary for this lecture yet."}
        </p>
      )}

      <div className="summary-points">
        {shown.map((point, i) => {
          const seconds = point.time ? toSeconds(point.time) : null;
          return seconds !== null && onSeek ? (
            <button
              key={`${point.time}-${i}`}
              className="summary-point"
              onClick={() => onSeek(seconds)}
              title="Jump to this moment"
            >
              <span className="summary-time">{point.time}</span>
              <span>{point.text}</span>
            </button>
          ) : (
            <div key={`${point.time}-${i}`} className="summary-point static">
              {point.time && <span className="summary-time">{point.time}</span>}
              <span>{point.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default LiveSummaryPanel;
