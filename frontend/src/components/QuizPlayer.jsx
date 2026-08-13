import React, { useState } from 'react';
import MathText from './MathText';
import styles from '../styles/QuizPlayer.module.css';

const apiBase = import.meta.env.VITE_API_BASE_URL || '';
const OPTIONS = [1, 2, 3, 4];

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
  const [finished, setFinished]     = useState(false);

  const current = questions[idx];
  const { subject = '', month = '', year = '' } = current;

  // Check user's answer
  const handleCheck = () => {
    const correct = String(selected) === String(current.correct_answer);
    setIsCorrect(correct);
    if (correct) setScore(s => s + 1);
    else setMissed(m => [...m, current]);
    setShowAnswer(true);
  };

  // Next question or finish
  const handleNext = () => {
    setShowAnswer(false);
    setSel(null);
    if (idx + 1 < questions.length) {
      setIdx(i => i + 1);
    } else {
      setFinished(true);
    }
  };

  if (finished) {
    return (
      <div className={styles.quizContainer}>
        <button onClick={onFinish} className={styles.closeBtn} aria-label="Close quiz">
          &times;
        </button>
        <span className={styles.eyebrow}>Quiz Complete</span>
        <div className={styles.scoreRow}>
          <span className={styles.scoreValue}>{score}</span>
          <span className={styles.scoreDivider}>/</span>
          <span className={styles.scoreTotal}>{questions.length}</span>
        </div>

        {missed.length === 0 ? (
          <p className={styles.perfectNote}>Every question, correct. Nice work.</p>
        ) : (
          <div className={styles.reviewSection}>
            <span className={styles.eyebrow}>Review Your Misses</span>
            {missed.map((q, i) => (
              <div key={`${q.id}-${i}`} className={styles.reviewCard}>
                <div className={styles.reviewMeta}>
                  {q.subject} &middot; {q.topic} &middot; correct answer: {q.correct_answer}
                </div>
                {q.explanation ? (
                  <div className={styles.explanationBox}>
                    <span className={styles.whyLabel}>Why</span>
                    <MathText>{q.explanation}</MathText>
                  </div>
                ) : (
                  <p className={styles.explanationPending}>
                    Explanation not generated yet for this question — check back soon.
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        <button onClick={onFinish} className={styles.nextBtn}>
          Close
        </button>
      </div>
    );
  }

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
        src={`${apiBase}/${current.question_image_path}`}
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
          {/* MCQ options 1–4, styled as scantron bubbles */}
          {current.type === 'MCQ' && (
            <div className={styles.options}>
              {OPTIONS.map(num => (
                <button
                  key={num}
                  onClick={() => setSel(num)}
                  className={styles.optionBtn}
                  aria-pressed={selected === num}
                >
                  <span className={`${styles.bubble} ${selected === num ? styles.bubbleFilled : ''}`}>
                    {num}
                  </span>
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
              className={styles.freeResponseInput}
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
        <div className={styles.feedback}>
          <p className={isCorrect ? styles.correctMsg : styles.incorrectMsg}>
            {isCorrect ? (
              <>✅ Correct!</>
            ) : (
              <>❌ Incorrect. The correct answer was <strong>{current.correct_answer}</strong>.</>
            )}
          </p>

          {current.explanation ? (
            <div className={styles.explanationBox}>
              <span className={styles.whyLabel}>Why</span>
              <MathText>{current.explanation}</MathText>
            </div>
          ) : (
            <p className={styles.explanationPending}>
              Explanation not generated yet for this question — check back soon.
            </p>
          )}

          <button onClick={handleNext} className={styles.nextBtn}>
            {idx + 1 < questions.length ? 'Next Question' : 'Finish Quiz'}
          </button>
        </div>
      )}
    </div>
  );
}
