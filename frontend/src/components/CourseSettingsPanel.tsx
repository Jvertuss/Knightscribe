import type { CourseSettings } from "../data/mockData";

interface CourseSettingsPanelProps {
  settings: CourseSettings;
  onChange: (settings: CourseSettings) => void;
}

interface Option {
  key: keyof CourseSettings;
  label: string;
  description: string;
  needsAi?: boolean;
}

const options: Option[] = [
  {
    key: "aiHelpEnabled",
    label: "AI help",
    description: "Master switch. When off, students can't use the chatbot at all.",
  },
  {
    key: "allowHints",
    label: "Hints",
    description: "The chatbot can nudge students toward an answer without giving it.",
    needsAi: true,
  },
  {
    key: "allowExplanations",
    label: "Explanations",
    description: "The chatbot can explain a concept from the lecture.",
    needsAi: true,
  },
  {
    key: "allowFinalAnswers",
    label: "Final answers",
    description: "The chatbot can give the full answer to a question.",
    needsAi: true,
  },
  {
    key: "allowPracticeQuestions",
    label: "Practice questions",
    description: "Students can take the practice quiz for each lecture.",
  },
  {
    key: "allowRecordings",
    label: "Recordings",
    description:
      "Students can rewatch a lecture after its livestream ends. Live streams are always watchable.",
  },
];

function CourseSettingsPanel({ settings, onChange }: CourseSettingsPanelProps) {
  return (
    <div className="teacher-panel">
      <h3>Course settings</h3>
      <p className="panel-note">Changes save right away for everyone in this course.</p>
      {options.map((opt) => {
        const disabled = opt.needsAi && !settings.aiHelpEnabled;
        return (
          <label
            key={opt.key}
            className={disabled ? "settings-row disabled" : "settings-row"}
          >
            <div>
              <strong>{opt.label}</strong>
              <div className="settings-desc">{opt.description}</div>
            </div>
            <input
              type="checkbox"
              className="switch"
              checked={settings[opt.key]}
              disabled={disabled}
              onChange={(e) =>
                onChange({ ...settings, [opt.key]: e.target.checked })
              }
            />
          </label>
        );
      })}
    </div>
  );
}

export default CourseSettingsPanel;