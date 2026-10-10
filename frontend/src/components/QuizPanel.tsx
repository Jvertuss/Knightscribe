import { useState } from "react";
import type { QuizQuestion } from "../data/mockData";

interface QuizPanelProps {
  questions: QuizQuestion[];
}

function QuizPanel({ questions }: QuizPanelProps) {
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [score, setScore] = useState(0);
  const [finished, setFinished] = useState(false);

  if (questions.length === 0) {
    return (
      <div className="quiz-panel">
        <h3>Practice Quiz</h3>
        <p>No quiz for this lecture yet.</p>
      </div>
    );
  }

  const question = questions[index];

  function handlePick(choiceIndex: number) {
    if (picked !== null) return; // already answered
    setPicked(choiceIndex);
    if (choiceIndex === question.answerIndex) {
      setScore(score + 1);
    }
  }

  function handleNext() {
    if (index + 1 >= questions.length) {
      setFinished(true);
    } else {
      setIndex(index + 1);
      setPicked(null);
    }
  }

  function handleRestart() {
    setIndex(0);
    setPicked(null);
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
        if (picked !== null) {
          if (i === question.answerIndex) className += " correct";
          else if (i === picked) className += " wrong";
        }
        return (
          <button key={i} className={className} onClick={() => handlePick(i)}>
            {choice}
          </button>
        );
      })}

      {picked !== null && (
        <button className="quiz-btn" onClick={handleNext}>
          {index + 1 >= questions.length ? "See score" : "Next question"}
        </button>
      )}
    </div>
  );
}

export default QuizPanel;