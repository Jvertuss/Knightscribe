import { useEffect, useState } from "react";
import type { SummaryPoint } from "../data/mockData";

interface LiveSummaryPanelProps {
  points: SummaryPoint[];
  isLive: boolean;
  onSeek?: (seconds: number) => void;
}

// "01:30" -> 90
function toSeconds(time: string) {
  const [minutes, seconds] = time.split(":").map(Number);
  return minutes * 60 + seconds;
}

function LiveSummaryPanel({ points, isLive, onSeek }: LiveSummaryPanelProps) {
  const [visibleCount, setVisibleCount] = useState(
    isLive ? Math.min(1, points.length) : points.length
  );

  // TODO (AI teammate): replace this fake timer with real data, e.g.
  // GET /api/lectures/:id/summary  ->  SummaryPoint[]  (poll every few seconds)
  useEffect(() => {
    if (!isLive) return;
    const timer = setInterval(() => {
      setVisibleCount((count) => (count < points.length ? count + 1 : count));
    }, 4000);
    return () => clearInterval(timer);
  }, [isLive, points.length]);

  // newest first
  const visible = points.slice(0, visibleCount).reverse();

  return (
    <div className="summary-panel">
      <div className="summary-header">
        <h3>{isLive ? "Live Summary" : "Summary"}</h3>
        {isLive && <span className="live-badge">LIVE</span>}
      </div>

      {visible.length === 0 && <p>Waiting for the lecture to start...</p>}

      <div className="summary-points">
        {visible.map((point, i) => (
          <button
            key={`${point.time}-${i}`}
            className="summary-point"
            onClick={() => onSeek?.(toSeconds(point.time))}
          >
            <span className="summary-time">{point.time}</span>
            <span>{point.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default LiveSummaryPanel;