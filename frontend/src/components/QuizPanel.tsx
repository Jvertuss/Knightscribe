import { useEffect, useState } from "react";
import type { Lecture, QuizQuestion } from "../data/mockData";
import { answerQuiz, fetchQuiz } from "../backend";

interface QuizPanelProps {
  lecture: Lecture;
}

// What the student sees after picking an answer
interface Checked {
  picked: number;
  correctOption: number;
  explanation: string | null;
}

function QuizPanel({ lecture }: QuizPanelProps) {
  // backend lectures load their questions; mock lectures use their own
  const [questions, setQuestions] = useState<QuizQuestion[] | null>(
    lecture.backendId ? null : lecture.quiz
  );
  const [index, setIndex] = useState(0);
  const [checked, setChecked] = useState<Checked | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [score, setScore] = useState(0);
  const [finished, setFinished] = useState(false);

  useEffect(() => {
    if (!lecture.backendId) return;
    let cancelled = false;
    fetchQuiz(lecture.backendId).then((list) => {
      if (!cancelled) setQuestions(list);
    });
    return () => {
      cancelled = true;
    };
  }, [lecture.backendId]);

  if (questions === null) {
    return (
      <div className="quiz-panel">
        <h3>Practice Quiz</h3>
        <p>Loading questions...</p>
      </div>
    );
  }

  if (questions.length === 0) {
    return (
      <div className="quiz-panel">
        <h3>Practice Quiz</h3>
        <p>No quiz for this lecture yet.</p>
      </div>
    );
  }

  const question = questions[index];

  async function handlePick(choiceIndex: number) {
    if (checked || checking) return; // already answered
    setError("");
    let result: Checked;
    if (question.backendId !== undefined) {
      // the server knows the right answer; the page doesn't
      setChecking(true);
      try {
        const r = await answerQuiz(question.backendId, choiceIndex);
        result = { picked: choiceIndex, correctOption: r.correctOption, explanation: r.explanation };
      } catch (err) {
        setError((err as Error).message);
        setChecking(false);
        return;
      }
      setChecking(false);
    } else {
      result = { picked: choiceIndex, correctOption: question.answerIndex, explanation: null };
    }
    setChecked(result);
    if (result.picked === result.correctOption) setScore((s) => s + 1);
  }

  function handleNext() {
    if (!questions) return;
    if (index + 1 >= questions.length) {
      setFinished(true);
    } else {
      setIndex(index + 1);
      setChecked(null);
    }
  }

  function handleRestart() {
    setIndex(0);
    setChecked(null);
    setScore(0);
    setFinished(false);
  }

  if (finished) {
    return (
      <div className="quiz-panel">
        <h3>Practice Quiz</h3>
        <p>
          You scored {score} out of {questions.length}.
        </p>
        <button className="quiz-btn" onClick={handleRestart}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="quiz-panel">
      <h3>Practice Quiz</h3>
      <p>
        Question {index + 1} of {questions.length}
      </p>
      <h4>{question.question}</h4>

      {question.choices.map((choice, i) => {
        let className = "quiz-choice";
        if (checked) {
          if (i === checked.correctOption) className += " correct";
          else if (i === checked.picked) className += " wrong";
        }
        return (
          <button
            key={i}
            className={className}
            onClick={() => handlePick(i)}
            disabled={checking}
          >
            {choice}
          </button>
        );
      })}

      {checking && <p className="quiz-note">Checking...</p>}
      {error && <p className="quiz-error">{error}</p>}
      {checked && (
        <p className={checked.picked === checked.correctOption ? "quiz-result right" : "quiz-result"}>
          {checked.picked === checked.correctOption ? "Correct!" : "Not quite."}
          {checked.explanation ? ` ${checked.explanation}` : ""}
        </p>
      )}

      {checked && (
        <button className="quiz-btn" onClick={handleNext}>
          {index + 1 >= questions.length ? "See score" : "Next question"}
        </button>
      )}
    </div>
  );
}

export default QuizPanel;
