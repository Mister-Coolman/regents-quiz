import React, { useState } from 'react';
import MathText from './MathText';
import { buildHints } from '../lib/explanation';
import styles from '../styles/QuizPlayer.module.css';

const apiBase = import.meta.env.VITE_API_BASE_URL || '';
const OPTIONS = [1, 2, 3, 4];

/** Full explanation behind a disclosure, so the answer isn't dumped on sight. */
function ExplanationPanel({ text, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!text) {
    return (
      <p className={styles.explanationPending}>
        Explanation not available for this question yet.
      </p>
    );
  }
  return (
    <div className={styles.disclosure}>
      <button
        type="button"
        className={styles.disclosureToggle}
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span className={styles.caret} data-open={open}>▸</span>
        {open ? 'Hide explanation' : 'Show explanation'}
      </button>
      {open && (
        <div className={styles.explanationBox}>
          <MathText>{text}</MathText>
        </div>
      )}
    </div>
  );
}

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
  // How many hints the student has unlocked on the current question.
  const [hintLevel, setHintLevel]   = useState(0);

  const current = questions[idx];
  const { subject = '', month = '', year = '' } = current;

  const hints = buildHints(current.explanation);
  const shownHints = hints.slice(0, hintLevel);
  const hintsLeft = hints.length - hintLevel;

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
    setHintLevel(0);
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
                <ExplanationPanel text={q.explanation} />
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

          {/* Hints unlock one at a time while the student is still working:
              the framing, then the method, then the opening steps -- stopping
              short of the full solution. */}
          {hints.length > 0 && (
            <div className={styles.hintArea}>
              {shownHints.map((h, i) => (
                <div key={i} className={styles.hint}>
                  <span className={styles.hintLabel}>{h.label}</span>
                  <MathText>{h.body}</MathText>
                </div>
              ))}

              {hintsLeft > 0 ? (
                <button
                  type="button"
                  className={styles.hintBtn}
                  onClick={() => setHintLevel(l => l + 1)}
                >
                  💡 {hintLevel === 0 ? 'Need a hint?' : 'Another hint'}
                  <span className={styles.hintCount}>{hintsLeft} left</span>
                </button>
              ) : (
                <p className={styles.hintExhausted}>
                  That's every hint — give it a go, then check your answer.
                </p>
              )}
            </div>
          )}
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

          {/* Opened by default when they got it wrong -- that's the moment the
              explanation is worth reading -- and collapsed when they got it
              right, so a correct answer isn't buried under a wall of text. */}
          <ExplanationPanel text={current.explanation} defaultOpen={!isCorrect} />

          <button onClick={handleNext} className={styles.nextBtn}>
            {idx + 1 < questions.length ? 'Next Question' : 'Finish Quiz'}
          </button>
        </div>
      )}
    </div>
  );
}
