import React, { useState } from 'react';
import styles from '../styles/QuizPlayer.module.css';

const apiBase = import.meta.env.VITE_API_BASE_URL || '';

export default function QuizPlayer({ questions = [], onFinish }) {
  // 1) Guard against empty questions
  if (!Array.isArray(questions) || questions.length === 0) {
    return (
      <div style={{ padding: '1rem', textAlign: 'center' }}>
        <strong>Loading quiz…</strong>
      </div>
    );
  }

  const [idx, setIdx]               = useState(0);
  const [selected, setSel]          = useState(null);
  const [score, setScore]           = useState(0);
  const [missed, setMissed]         = useState([]);
  const [showAnswer, setShowAnswer] = useState(false);
  const [isCorrect, setIsCorrect]   = useState(false);

  const current = questions[idx];
  const { subject = '', month = '', year = '' } = current;

  // Check user's answer
  const handleCheck = () => {
    const correct = String(selected) === String(current.correct_answer);
    setIsCorrect(correct);
    if (correct) setScore(s => s + 1);
    else setMissed(m => [...m, current.id]);
    setShowAnswer(true);
  };

  // Next question or finish
  const handleNext = () => {
    setShowAnswer(false);
    setSel(null);
    if (idx + 1 < questions.length) {
      setIdx(i => i + 1);
    } else {
      alert(`Quiz complete! Your score: ${score}/${questions.length}`);
      onFinish();
    }
  };

  return (
    <div className={styles.quizContainer}>
      {/* ✖️ Close button */}
      <button onClick={onFinish} className={styles.closeBtn} aria-label="Close quiz">
        &times;
      </button>

      {/* Combined header row */}
      <div className={styles.headerRow}>
        <h2 className={styles.questionCount}>
          Question {idx + 1} of {questions.length}
        </h2>
        <div className={styles.metadata}>
          {subject} – {month} {year}
        </div>
      </div>

      {/* Question image */}
      {current.question_image_path && (
        <img
        src={`${apiBase}${current.question_image_path}`}
          alt="Question diagram"
          style={{
            width: '100%',
            maxHeight: 300,
            objectFit: 'contain',
            marginBottom: 16
          }}
        />
      )}

      {/* Question text */}
      <p className={styles.questionText}>{current.question_text}</p>

      {!showAnswer ? (
        <>
          {/* MCQ options 1–4 */}
          {current.type === 'MCQ' && (
            <div className={styles.options}>
              {[1, 2, 3, 4].map(num => (
                <button
                  key={num}
                  onClick={() => setSel(num)}
                  className={`${styles.optionBtn} ${
                    selected === num ? styles.selected : ''
                  }`}
                >
                  {num}
                </button>
              ))}
            </div>
          )}

          {/* Free-response if not MCQ */}
          {current.type !== 'MCQ' && (
            <input
              type="text"
              value={selected || ''}
              onChange={e => setSel(e.target.value)}
              placeholder="Type your answer"
              style={{
                width: '100%',
                padding: 8,
                marginBottom: 16,
                borderRadius: 4,
                border: '1px solid #ccc'
              }}
            />
          )}

          <button
            onClick={handleCheck}
            disabled={selected === null || selected === ''}
            className={styles.checkBtn}
          >
            Check Answer
          </button>
        </>
      ) : (
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: '1.1rem', margin: '1rem 0' }}>
            {isCorrect ? (
              <span style={{ color: '#10b981' }}>✅ Correct!</span>
            ) : (
              <span style={{ color: '#ef4444' }}>
                ❌ Incorrect. The correct answer was{' '}
                <strong>{current.correct_answer}</strong>.
              </span>
            )}
          </p>
          <button onClick={handleNext} className={styles.nextBtn}>
            {idx + 1 < questions.length ? 'Next Question' : 'Finish Quiz'}
          </button>
        </div>
      )}
    </div>
  );
}