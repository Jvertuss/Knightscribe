import { useEffect, useRef } from "react";
import type { TranscriptLine } from "../data/mockData";

interface TranscriptPanelProps {
  lines: TranscriptLine[];
}

function TranscriptPanel({ lines }: TranscriptPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div className="transcript-panel">
      <h3>Live Transcript</h3>
      <div className="transcript-lines">
        {lines.map((line, i) => (
          <p key={i}>
            <span className="transcript-time">{line.time}</span> {line.text}
          </p>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

export default TranscriptPanel;