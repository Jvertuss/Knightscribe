import type {
  Lecture,
  CourseSettings,
  TranscriptLine,
  SummaryPoint,
  QuizQuestion,
} from "./data/mockData";

export type ChatMode = "ask" | "hint" | "explain" | "answer";

function findBestLine(lecture: Lecture, message: string): TranscriptLine | null {
  const words = message
    .toLowerCase()
    .split(/\W+/)
    .filter((w) => w.length > 3);

  let best: TranscriptLine | null = null;
  let bestScore = 0;

  for (const line of lecture.transcript) {
    const score = words.filter((w) => line.text.toLowerCase().includes(w)).length;
    if (score > bestScore) {
      bestScore = score;
      best = line;
    }
  }
  return best;
}

// TODO (AI teammate): replace the body with a real call, e.g.
// POST /api/chat  { lectureId, message, mode }  ->  { reply }
// The SERVER should load the course settings itself and apply them to the AI
// prompt. It should not trust the settings sent from the browser.
export async function sendChatMessage(
  lecture: Lecture,
  message: string,
  mode: ChatMode,
  settings: CourseSettings
): Promise<string> {
  await new Promise((resolve) => setTimeout(resolve, 700)); // fake thinking time

  // Checked here too, not just in the buttons
  if (!settings.aiHelpEnabled) return "AI help is turned off for this course.";
  if (mode === "hint" && !settings.allowHints)
    return "Your teacher has turned off hints for this course.";
  if (mode === "explain" && !settings.allowExplanations)
    return "Your teacher has turned off explanations for this course.";
  if (mode === "answer" && !settings.allowFinalAnswers)
    return "Your teacher has turned off final answers for this course.";

  const line = findBestLine(lecture, message);
  if (!line) {
    return "I couldn't find that in this lecture yet. Try asking about a topic from the transcript.";
  }

  if (mode === "hint") {
    return `Hint: revisit the part of the lecture around ${line.time} and think about the key term there.`;
  }
  if (mode === "explain") {
    return `Here's the idea from ${line.time}: ${line.text} Try restating it in your own words.`;
  }
  if (mode === "answer") {
    return `Answer: ${line.text}`;
  }
  return `That topic comes up around ${line.time} in the lecture.`;
}

// Turns pasted text into transcript lines.
// Lines like "00:41 So 1010 equals ten" keep their time; lines without a time
// get a placeholder time, spaced 20 seconds apart.
export function parseTranscript(text: string): TranscriptLine[] {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  return lines.map((line, i) => {
    const match = line.match(/^(\d{1,2}:\d{2})\s+(.*)$/);
    if (match) return { time: match[1], text: match[2] };

    const total = i * 20;
    const mm = String(Math.floor(total / 60)).padStart(2, "0");
    const ss = String(total % 60).padStart(2, "0");
    return { time: `${mm}:${ss}`, text: line };
  });
}

// TODO (AI teammate): replace with a real call, e.g.
// POST /api/lectures/generate  { transcript }  ->  { liveSummary, quiz }
// This placeholder just picks a few transcript lines as the "summary".
export async function generateFromTranscript(
  transcript: TranscriptLine[]
): Promise<{ liveSummary: SummaryPoint[]; quiz: QuizQuestion[] }> {
  await new Promise((resolve) => setTimeout(resolve, 800)); // fake thinking time

  const step = Math.max(1, Math.floor(transcript.length / 4));
  const liveSummary = transcript
    .filter((_, i) => i % step === 0)
    .slice(0, 4)
    .map((line) => ({ time: line.time, text: line.text }));

  return { liveSummary, quiz: [] };
}