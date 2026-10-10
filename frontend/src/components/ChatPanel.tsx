import { useEffect, useRef, useState } from "react";
import type { Lecture, ChatMessage, CourseSettings } from "../data/mockData";
import { greeting } from "../data/mockData";
import { sendChatMessage } from "../api";
import type { ChatMode } from "../api";

interface ChatPanelProps {
  lecture: Lecture;
  settings: CourseSettings;
}

function ChatPanel({ lecture, settings }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([greeting]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [mode, setMode] = useState<ChatMode>("ask");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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

    const reply = await sendChatMessage(lecture, text, activeMode, settings);

    setMessages((prev) => [...prev, { role: "bot", text: reply }]);
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

      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            {m.text}
          </div>
        ))}
        {waiting && <div className="chat-bubble bot">Thinking...</div>}
        <div ref={bottomRef} />
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