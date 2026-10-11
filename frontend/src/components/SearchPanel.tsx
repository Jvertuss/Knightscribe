import { useState } from "react";
import { searchCourse } from "../backend";
import type { SearchResult } from "../backend";

interface SearchPanelProps {
  courseId: number;
  // open a lecture at a moment; returns false if that lecture isn't available
  onOpen: (backendLectureId: string, seconds: number | null) => boolean;
}

const clock = (s: number) =>
  `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// The searched words in bold inside a result
function highlight(text: string, query: string) {
  const words = query.toLowerCase().match(/[a-z0-9]{2,}/g) ?? [];
  if (words.length === 0) return text;
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(pattern).map((part, i) =>
    i % 2 === 1 ? <mark key={i}>{part}</mark> : part
  );
}

const LABEL: Record<SearchResult["type"], string> = {
  transcript: "Said in lecture",
  whiteboard: "On the board",
  document: "Reference material",
};

// "Find the moment": search everything said, written and uploaded in the course
function SearchPanel({ courseId, onOpen }: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searched, setSearched] = useState(""); // the query the results are for
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSearch() {
    const q = query.trim();
    if (q.length < 2 || busy) return;
    setBusy(true);
    setError("");
    try {
      setResults(await searchCourse(courseId, q));
      setSearched(q);
    } catch {
      setError("Search isn't available right now. Try again in a moment.");
      setResults(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="search-panel">
      <div className="search-row">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Search everything said, written or uploaded in this course..."
          aria-label="Search the course"
        />
        <button onClick={handleSearch} disabled={busy || query.trim().length < 2}>
          {busy ? "Searching..." : "Search"}
        </button>
        {results && (
          <button className="search-clear" onClick={() => setResults(null)}>
            Clear
          </button>
        )}
      </div>

      {error && <p className="teacher-error">{error}</p>}
      {results && results.length === 0 && (
        <p className="empty-note">Nothing found for "{query.trim()}".</p>
      )}
      {results && results.length > 0 && (
        <div className="search-results">
          {results.map((r, i) => {
            const canOpen = r.type !== "document" && r.lectureId !== null;
            const where =
              r.type === "document"
                ? r.location ?? ""
                : r.seconds !== null
                ? `at ${clock(r.seconds)}`
                : "";
            return (
              <button
                key={i}
                className={canOpen ? "search-result link" : "search-result"}
                disabled={!canOpen}
                onClick={() => {
                  if (canOpen && !onOpen(r.lectureId as string, r.seconds)) {
                    setError("That lecture isn't available to students.");
                  }
                }}
              >
                <span className="search-meta">
                  {LABEL[r.type]} · {r.title} {where && `· ${where}`}
                </span>
                <span className="search-content">{highlight(r.content, searched)}</span>
                {canOpen && <span className="search-go">Open at this moment →</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default SearchPanel;
