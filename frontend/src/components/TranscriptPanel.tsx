import { useEffect, useRef } from "react";
import type { TranscriptLine } from "../data/mockData";

interface TranscriptPanelProps {
  lines: TranscriptLine[];
  isLive?: boolean;
}

function TranscriptPanel({ lines, isLive = false }: TranscriptPanelProps) {
  const boxRef = useRef<HTMLDivElement>(null);

  // keep the newest line in view by scrolling the box, not the whole page
  useEffect(() => {
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
    // only when a line is added: a refresh must not yank the student back down
  }, [lines.length]);

  return (
    <div className="transcript-panel">
      <h3>{isLive ? "Live Transcript" : "Transcript"}</h3>
      {lines.length === 0 && (
        <p className="empty-note">
          {isLive ? "Waiting for the professor to speak..." : "No transcript for this lecture."}
        </p>
      )}
      <div className="transcript-lines" ref={boxRef}>
        {lines.map((line, i) => (
          <p key={i}>
            <span className="transcript-time">{line.time}</span>
            {line.text}
          </p>
        ))}
      </div>
    </div>
  );
}

export default TranscriptPanel;
