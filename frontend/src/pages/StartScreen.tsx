import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import LetterBackground from "../components/LetterBackground";

type Role = "student" | "teacher";

interface StartScreenProps {
  onChoose: (role: Role) => void;
}

const TITLE = "Knight Scribe";

// Types the title one letter at a time with an uneven rhythm, like a real typist
function useTypewriter(text: string) {
  const [count, setCount] = useState(() =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? text.length
      : 0
  );

  useEffect(() => {
    if (count >= text.length) return;
    let delay = 150 + Math.random() * 110; // typing speed per letter
    if (count === 0) delay = 800; // pause before the first key
    if (text[count - 1] === " ") delay += 300; // pause after the space
    const timer = setTimeout(() => setCount(count + 1), delay);
    return () => clearTimeout(timer);
  }, [count, text]);

  return count;
}

const PUSH_MS = 450; // must match the push-out animation time in the CSS

function StartScreen({ onChoose }: StartScreenProps) {
  const count = useTypewriter(TITLE);
  const done = count >= TITLE.length;

  const screenRef = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState(false);
  const [origin, setOrigin] = useState("50% 50%");

  // Zoom into the button that was clicked, then switch screens
  function choose(role: Role, e: MouseEvent<HTMLButtonElement>) {
    if (leaving) return;

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (reduceMotion) {
      onChoose(role);
      return;
    }

    const screen = screenRef.current?.getBoundingClientRect();
    const button = e.currentTarget.getBoundingClientRect();
    if (screen) {
      setOrigin(
        `${button.left + button.width / 2 - screen.left}px ${
          button.top + button.height / 2 - screen.top
        }px`
      );
    }

    setLeaving(true);
    setTimeout(() => onChoose(role), PUSH_MS);
  }

  const className = ["start-screen", done && "is-done", leaving && "is-leaving"]
    .filter(Boolean)
    .join(" ");

  return (
    <>
      <LetterBackground />

      <div className={className} ref={screenRef} style={{ transformOrigin: origin }}>
        <img
          className="start-logo"
          src="/knight-logo.png"
          alt="Knight Scribe logo"
        />

        <h1 className="start-title" aria-label={TITLE}>
          <span aria-hidden="true">
            {TITLE.slice(0, count)}
            <span className={count === 0 || done ? "caret idle" : "caret"} />
            <span className="untyped">{TITLE.slice(count)}</span>
          </span>
        </h1>

        <p className="start-tagline">
          Live lectures, notes, and practice in one place
        </p>

        <div className="start-buttons">
          <button className="start-btn" onClick={(e) => choose("student", e)}>
            <span className="start-btn-label">Student</span>
          </button>
          <button className="start-btn" onClick={(e) => choose("teacher", e)}>
            <span className="start-btn-label">Teacher</span>
          </button>
        </div>
      </div>
    </>
  );
}

export default StartScreen;