import { useEffect, useRef, useState } from "react";
import type {
  Lecture,
  ChatMessage,
  ChatSource,
  CourseSettings,
} from "../data/mockData";
import { greeting } from "../data/mockData";
import { askAI } from "../backend";
import { sendChatMessage } from "../api";
import type { ChatMode } from "../api";

interface ChatPanelProps {
  lecture: Lecture;
  settings: CourseSettings;
  onSeek?: (seconds: number) => void; // jump the video to a cited moment
}

// 75 -> "1:15"
const clock = (s: number) =>
  `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// One citation under an AI answer. Moments in the open lecture are buttons
// that jump the video there; everything else is a plain label.
function SourceChip({
  source,
  lecture,
  onSeek,
}: {
  source: ChatSource;
  lecture: Lecture;
  onSeek?: (seconds: number) => void;
}) {
  if (source.type === "video") {
    return <span className="source-chip">Lecture video</span>;
  }
  if (source.type === "document") {
    return (
      <span className="source-chip">
        {source.title}
        {source.location ? ` · ${source.location}` : ""}
      </span>
    );
  }
  const what = source.type === "board_event" ? "Board" : "Lecture";
  const sameLecture = source.lectureId === lecture.backendId;
  if (sameLecture && source.seconds !== null && onSeek) {
    const seconds = source.seconds;
    return (
      <button
        className="source-chip link"
        onClick={() => onSeek(seconds)}
        title="Jump to this moment"
      >
        ▶ {what} {clock(seconds)}
      </button>
    );
  }
  return (
    <span className="source-chip">
      {sameLecture ? what : source.title}
      {source.seconds !== null ? ` ${clock(source.seconds)}` : ""}
    </span>
  );
}

function ChatPanel({ lecture, settings, onSeek }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([greeting]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [mode, setMode] = useState<ChatMode>("ask");
  const messagesRef = useRef<HTMLDivElement>(null);

  // keep the newest message in view by scrolling the box, not the whole page
  useEffect(() => {
    const box = messagesRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [messages, waiting]);

  if (!settings.aiHelpEnabled) {
    return (
      <div className="chat-panel">
        <h3>Ask the AI</h3>
        <p>AI help is turned off for this course.</p>
      </div>
    );
  }

  const modes: { id: ChatMode; label: string; allowed: boolean }[] = [
    { id: "ask", label: "Ask", allowed: true },
    { id: "hint", label: "Hint", allowed: settings.allowHints },
    { id: "explain", label: "Explain", allowed: settings.allowExplanations },
    { id: "answer", label: "Final answer", allowed: settings.allowFinalAnswers },
  ];

  // fall back to "ask" if the selected mode gets turned off
  const activeMode = modes.find((m) => m.id === mode && m.allowed) ? mode : "ask";

  async function handleSend() {
    const text = input.trim();
    if (!text || waiting) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setWaiting(true);

    let reply: ChatMessage;
    if (lecture.backendId) {
      // real lectures: the backend's AI, grounded in this course's material only
      try {
        const { answer, sources } = await askAI(
          lecture.courseId,
          lecture.backendId,
          text,
          activeMode
        );
        reply = { role: "bot", text: answer, sources };
      } catch (err) {
        reply = { role: "bot", text: (err as Error).message, error: true };
      }
    } else {
      // mock lectures (backend down): the offline stand-in
      reply = {
        role: "bot",
        text: await sendChatMessage(lecture, text, activeMode, settings),
      };
    }

    setMessages((prev) => [...prev, reply]);
    setWaiting(false);
  }

  return (
    <div className="chat-panel">
      <h3>Ask the AI</h3>

      <div className="chat-modes">
        {modes.map((m) => (
          <button
            key={m.id}
            className={m.id === activeMode ? "mode-btn active" : "mode-btn"}
            disabled={!m.allowed}
            title={m.allowed ? "" : "Turned off by your teacher"}
            onClick={() => setMode(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="chat-messages" ref={messagesRef}>
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}${m.error ? " error" : ""}`}>
            {m.text}
            {m.sources && m.sources.length > 0 && (
              <div className="chat-sources">
                {m.sources.map((s) => (
                  <SourceChip key={s.sourceId} source={s} lecture={lecture} onSeek={onSeek} />
                ))}
              </div>
            )}
          </div>
        ))}
        {waiting && <div className="chat-bubble bot thinking">Looking through your course material...</div>}
      </div>

      <div className="chat-input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask about this lecture..."
        />
        <button onClick={handleSend} disabled={waiting}>
          Send
        </button>
      </div>
    </div>
  );
}

export default ChatPanel;
