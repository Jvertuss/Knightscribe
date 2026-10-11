export interface TranscriptLine {
  time: string;
  text: string;
}

export interface SummaryPoint {
  time: string;
  text: string;
}

export interface QuizQuestion {
  id: number;
  question: string;
  choices: string[];
  answerIndex: number; // -1 for backend questions: the server checks the answer
  backendId?: number; // set for questions stored on the backend
}

// Where an AI answer came from: a reference document, or a moment in a lecture
export interface ChatSource {
  sourceId: string;
  type: "document" | "transcript" | "board_event";
  title: string;
  location: string | null; // e.g. "Slide 12"
  lectureId: string | null; // the backend lecture id
  seconds: number | null; // when it happened in that lecture
}

export interface ChatMessage {
  role: "user" | "bot";
  text: string;
  sources?: ChatSource[];
  error?: boolean;
}

export interface Course {
  id: number;
  title: string;
  instructor: string;
  description: string;
}

export interface Lecture {
  id: number;
  courseId: number;
  title: string;
  backendId?: string; // the real id from the API, e.g. "lecture_2026-10-10_11-30-00"
  local?: boolean; // added by the teacher in this browser, not on the backend
  videoUrl: string;
  isLive: boolean;
  published: boolean;
  completed: boolean;
  transcript: TranscriptLine[];
  liveSummary: SummaryPoint[];
  quiz: QuizQuestion[];
}

// Kept so LessonCard.tsx, which imports "Lesson", still compiles
export type Lesson = Lecture;

export type ReferenceType = "textbook" | "slides" | "article" | "video";

export interface ReferenceMaterial {
  id: number;
  backendId?: number; // set for documents stored on the backend (the AI can cite these)
  courseId: number;
  lectureId?: number; // leave out for course-wide material
  title: string;
  type: ReferenceType;
  source: string;
  url?: string;
}

export interface Chapter {
  id: number;
  lectureId: number;
  startSeconds: number; // offset from the start of the video or stream
  title: string;
  snapshotUrl: string; // photo the classroom camera saved
}

export interface CourseSettings {
  aiHelpEnabled: boolean;
  allowHints: boolean;
  allowExplanations: boolean;
  allowFinalAnswers: boolean;
  allowPracticeQuestions: boolean;
  allowRecordings: boolean;
}

export const greeting: ChatMessage = {
  role: "bot",
  text: "Hi! Ask me anything about this lecture. I answer only from your course material and lectures.",
};

export const defaultSettings: CourseSettings = {
  aiHelpEnabled: true,
  allowHints: true,
  allowExplanations: true,
  allowFinalAnswers: false,
  allowPracticeQuestions: true,
  allowRecordings: true,
};

export const courses: Course[] = [
  {
    id: 1,
    title: "KnightScribe Demo Course",
    instructor: "Demo Professor",
    description: "KNT 1000",
  },
];

export const lectures: Lecture[] = [
  {
    id: 1,
    courseId: 1,
    title: "Intro to Binary",
    videoUrl: "https://www.youtube.com/embed/Ieq8AR8krrA",
    isLive: true,
    published: true,
    completed: false,
    transcript: [
      { time: "00:05", text: "Today we're covering how binary numbers work." },
      { time: "00:20", text: "Each digit is a bit, and it can only be zero or one." },
      { time: "00:41", text: "So 1010 in binary equals ten in decimal." },
    ],
    liveSummary: [
      { time: "00:20", text: "Binary uses only two digits, 0 and 1, called bits." },
      { time: "00:41", text: "Example: 1010 in binary = 10 in decimal." },
    ],
    quiz: [
      {
        id: 1,
        question: "What is 1010 in decimal?",
        choices: ["8", "10", "12", "14"],
        answerIndex: 1,
      },
    ],
  },
  {
    id: 2,
    courseId: 1,
    title: "Logic Gates",
    videoUrl: "https://www.youtube.com/embed/INEtYZqtjTo",
    isLive: false,
    published: true,
    completed: false,
    transcript: [
      { time: "00:04", text: "Logic gates take binary inputs and produce one output." },
      { time: "00:18", text: "An AND gate outputs one only when both inputs are one." },
      { time: "00:35", text: "An OR gate outputs one when at least one input is one." },
    ],
    liveSummary: [
      { time: "00:18", text: "AND gate: output is 1 only if both inputs are 1." },
      { time: "00:35", text: "OR gate: output is 1 if at least one input is 1." },
    ],
    quiz: [
      {
        id: 1,
        question: "An AND gate outputs 1 when...",
        choices: [
          "Either input is 1",
          "Both inputs are 1",
          "Both inputs are 0",
          "The inputs are different",
        ],
        answerIndex: 1,
      },
    ],
  },
];

export const references: ReferenceMaterial[] = [
  {
    id: 1,
    courseId: 1,
    title: "Digital Logic Textbook, Chapter 1: Number Systems",
    type: "textbook",
    source: "Course textbook",
  },
  {
    id: 2,
    courseId: 1,
    lectureId: 1,
    title: "Intro to Binary: lecture slides",
    type: "slides",
    source: "Dr. Rivera",
  },
  {
    id: 3,
    courseId: 1,
    lectureId: 2,
    title: "Logic gate truth tables cheat sheet",
    type: "article",
    source: "Course website",
  },
];

export const chapters: Chapter[] = [
  {
    id: 1,
    lectureId: 1,
    startSeconds: 0,
    title: "What is binary?",
    snapshotUrl: "https://placehold.co/320x180/2d3250/ffffff?text=Binary+intro",
  },
  {
    id: 2,
    lectureId: 1,
    startSeconds: 30,
    title: "Bits and place values",
    snapshotUrl: "https://placehold.co/320x180/2d3250/ffffff?text=Bits",
  },
  {
    id: 3,
    lectureId: 1,
    startSeconds: 60,
    title: "Converting to decimal",
    snapshotUrl: "https://placehold.co/320x180/2d3250/ffffff?text=Converting",
  },
  {
    id: 4,
    lectureId: 2,
    startSeconds: 0,
    title: "What is a logic gate?",
    snapshotUrl: "https://placehold.co/320x180/2d3250/ffffff?text=Gates",
  },
  {
    id: 5,
    lectureId: 2,
    startSeconds: 30,
    title: "AND and OR",
    snapshotUrl: "https://placehold.co/320x180/2d3250/ffffff?text=AND+OR",
  },
];