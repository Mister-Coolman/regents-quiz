import React, { useState, useEffect } from 'react';
import MathText from './MathText';
import Confetti from './Confetti';
import SubjectMark from './SubjectMark';
import ScoreDial from './ScoreDial';
import { buildHints } from '../lib/explanation';
import styles from '../styles/QuizPlayer.module.css';

const apiBase = import.meta.env.VITE_API_BASE_URL || '';
const OPTIONS = [1, 2, 3, 4];

// Progress lives in localStorage: it belongs to this device, and the backend
// session tables sit on an ephemeral disk that is wiped on every redeploy.
function loadProgress(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveProgress(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode or quota -- progress just won't persist */
  }
}

function clearProgress(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    /* nothing to do */
  }
}

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
        {open ? 'Hide explanation' : 'Show explanation'}
        <span className={styles.caret} data-open={open} aria-hidden="true">›</span>
      </button>
      {open && (
        <div className={styles.explanationBox}>
          <MathText>{text}</MathText>
          <p className={styles.aiNote}>Written by AI. The answer key is from the exam.</p>
        </div>
      )}
    </div>
  );
}

export default function QuizPlayer({ questions = [], onFinish }) {
  // 1) Guard against empty questions
  if (!Array.isArray(questions) || questions.length === 0) {
    return (
      <p className={styles.loading}>Loading quiz…</p>
    );
  }

  // Progress is keyed by the exact set of questions, so reopening the same
  // quiz resumes while a different set starts clean.
  const storageKey = `regentsQuizProgress:${questions.map(q => q.id).join(',')}`;
  const saved = loadProgress(storageKey);

  const [idx, setIdx]               = useState(saved?.idx ?? 0);
  const [selected, setSel]          = useState(null);
  // One entry per answered question: { [questionId]: wasCorrect }. Deriving the
  // score from this instead of incrementing a counter keeps re-answering a
  // question idempotent -- which happens whenever someone closes the quiz
  // after checking an answer but before moving on, then reopens it.
  const [results, setResults]       = useState(saved?.results ?? {});
  const [showAnswer, setShowAnswer] = useState(false);
  const [isCorrect, setIsCorrect]   = useState(false);
  const [finished, setFinished]     = useState(saved?.finished ?? false);
  // How many hints the student has unlocked on the current question.
  const [hintLevel, setHintLevel]   = useState(0);
  // Shown when "Check answer" is pressed before choosing -- the button stays
  // enabled so it can explain itself instead of sitting greyed out.
  const [nudge, setNudge]           = useState(false);
  const [hintsUsed, setHintsUsed]   = useState(saved?.hintsUsed ?? 0);
  // Captured once at mount: true only when this run picked up stored progress,
  // rather than simply having advanced past the first question.
  const [wasResumed, setWasResumed] = useState(() => Object.keys(saved?.results ?? {}).length > 0);

  useEffect(() => {
    saveProgress(storageKey, { idx, results, hintsUsed, finished });
  }, [storageKey, idx, results, hintsUsed, finished]);

  const current = questions[idx];
  const { subject = '', month = '', year = '' } = current;
  const score = Object.values(results).filter(Boolean).length;
  const missed = questions.filter(q => results[q.id] === false);

  const hints = buildHints(current.explanation);
  const shownHints = hints.slice(0, hintLevel);
  const hintsLeft = hints.length - hintLevel;

  // Check user's answer
  const handleCheck = () => {
    if (selected === null || selected === '') {
      setNudge(true);
      return;
    }
    setNudge(false);
    const correct = String(selected) === String(current.correct_answer);
    setIsCorrect(correct);
    setResults(r => ({ ...r, [current.id]: correct }));
    setShowAnswer(true);
  };

  const handleRestart = () => {
    clearProgress(storageKey);
    setIdx(0);
    setSel(null);
    setResults({});
    setShowAnswer(false);
    setIsCorrect(false);
    setFinished(false);
    setHintLevel(0);
    setHintsUsed(0);
    setWasResumed(false);
  };

  // Next question or finish
  const handleNext = () => {
    setShowAnswer(false);
    setNudge(false);
    setSel(null);
    setHintLevel(0);
    if (idx + 1 < questions.length) {
      setIdx(i => i + 1);
    } else {
      setFinished(true);
    }
  };

  if (finished) {
    const perfect = questions.length > 0 && score === questions.length;
    return (
      <div className={styles.quiz}>
        {perfect && <Confetti />}
        <div className={styles.topbar}>
          <button onClick={onFinish} className={styles.backBtn}>
            <span aria-hidden="true">‹</span> Chat
          </button>
        </div>

        <section className={styles.results}>
          <ScoreDial
            results={questions.map(q => results[q.id])}
            score={score}
            total={questions.length}
          />
          <h2 className={styles.resultsHeadline}>
            {perfect
              ? 'Every question right.'
              : `${missed.length} to review.`}
          </h2>
          <p className={styles.resultsNote}>
            {hintsUsed === 0
              ? 'No hints used.'
              : `${hintsUsed} hint${hintsUsed === 1 ? '' : 's'} used.`}
          </p>
          <div className={styles.resultsActions}>
            <button onClick={onFinish} className={styles.primaryBtn}>
              Back to chat
            </button>
            <button onClick={handleRestart} className={styles.textBtn}>
              Retake this quiz
            </button>
          </div>
        </section>

        {missed.length > 0 && (
          <section className={styles.review}>
            <h3 className={styles.reviewHeading}>Questions to review</h3>
            {missed.map((q, i) => (
              <div key={`${q.id}-${i}`} className={styles.card}>
                <div className={styles.reviewMeta}>
                  <SubjectMark subject={q.subject} size={12} />
                  <span className={styles.reviewNumber}>Question {questions.indexOf(q) + 1}</span>
                  <span>{q.topic}</span>
                  <span className={styles.reviewAnswer}>Answer: {q.correct_answer}</span>
                </div>
                {q.question_image_path && (
                  <img
                    className={styles.reviewImage}
                    src={`${apiBase}/${q.question_image_path}`}
                    alt={`Diagram for question ${questions.indexOf(q) + 1}`}
                  />
                )}
                {q.question_text && <p className={styles.reviewQuestion}>{q.question_text}</p>}
                <ExplanationPanel text={q.explanation} />
              </div>
            ))}
          </section>
        )}
      </div>
    );
  }

  const isMCQ = current.type === 'MCQ';
  const bubbleState = (num) => {
    if (!showAnswer) return selected === num ? styles.bubbleFilled : '';
    if (String(num) === String(current.correct_answer)) return styles.bubbleCorrect;
    if (selected === num) return styles.bubbleWrong;
    return styles.bubbleDim;
  };

  return (
    <div className={styles.quiz}>
      <div className={styles.topbar}>
        <button onClick={onFinish} className={styles.backBtn}>
          <span aria-hidden="true">‹</span> Chat
        </button>
        <div className={styles.meta}>
          <SubjectMark subject={subject} size={12} />
          <span>{[subject, [month, year].filter(Boolean).join(' ')].filter(Boolean).join(', ')}</span>
        </div>
      </div>

      <div className={styles.counter}>
        <h2 className="sr-only">Question {idx + 1} of {questions.length}</h2>
        <span className={styles.counterNum} aria-hidden="true">{idx + 1}</span>
        <span className={styles.counterOf} aria-hidden="true">of {questions.length}</span>
        {wasResumed && <span className={styles.resumed}>Picked up where you left off</span>}
      </div>

      <div className={styles.card}>
        {current.question_image_path && (
          <img
            className={styles.questionImage}
            src={`${apiBase}/${current.question_image_path}`}
            alt="Diagram for this question"
          />
        )}

        <p className={styles.questionText}>{current.question_text}</p>

        {isMCQ ? (
          <fieldset className={styles.sheet}>
            <legend className="sr-only">Choose an answer</legend>
            {OPTIONS.map(num => (
              <label key={num} className={`${styles.bubble} ${bubbleState(num)}`}>
                <input
                  type="radio"
                  name={`answer-${current.id}`}
                  value={num}
                  checked={selected === num}
                  onChange={() => { setSel(num); setNudge(false); }}
                  disabled={showAnswer}
                  className={styles.bubbleInput}
                />
                <span aria-hidden="true">{num}</span>
                <span className="sr-only">
                  Choice {num}
                  {showAnswer && String(num) === String(current.correct_answer) ? ', correct answer' : ''}
                  {showAnswer && selected === num && String(num) !== String(current.correct_answer) ? ', your answer' : ''}
                </span>
              </label>
            ))}
          </fieldset>
        ) : (
          <input
            type="text"
            value={selected || ''}
            onChange={e => { setSel(e.target.value); setNudge(false); }}
            placeholder="Type your answer"
            aria-label="Your answer"
            disabled={showAnswer}
            className={styles.freeResponseInput}
          />
        )}

        {!showAnswer ? (
          <>
            <div className={styles.checkRow}>
              <button onClick={handleCheck} className={styles.primaryBtn}>
                Check answer
              </button>
              <p className={styles.nudge} role="alert">
                {nudge ? (isMCQ ? 'Choose an answer first.' : 'Type an answer first.') : ''}
              </p>
            </div>

            {/* Hints unlock one at a time while the student is still working:
                the framing, then the method, then the opening steps -- stopping
                short of the full solution. */}
            {hints.length > 0 && (
              <div className={styles.hintArea}>
                {shownHints.length > 0 && (
                  <p className={styles.aiNote}>Hints are taken from an AI-written explanation.</p>
                )}
                {shownHints.map((h, i) => (
                  <div key={i} className={styles.hint}>
                    <span className={styles.hintLabel}>{h.label}</span>
                    <MathText>{h.body}</MathText>
                  </div>
                ))}

                {hintsLeft > 0 ? (
                  <button
                    type="button"
                    className={styles.textBtn}
                    onClick={() => { setHintLevel(l => l + 1); setHintsUsed(n => n + 1); }}
                  >
                    {hintLevel === 0 ? 'Show a hint' : 'Show another hint'}
                    <span className={styles.hintCount}> ({hintsLeft} left)</span>
                  </button>
                ) : (
                  <p className={styles.hintExhausted}>
                    That's every hint. Give it a try, then check your answer.
                  </p>
                )}
              </div>
            )}
          </>
        ) : (
          <div className={styles.feedback}>
            <p className={isCorrect ? styles.correctMsg : styles.incorrectMsg} role="status">
              {isCorrect
                ? 'Correct.'
                : <>Not quite. The answer is <strong>{current.correct_answer}</strong>.</>}
            </p>

            {/* Opened by default when they got it wrong -- that's the moment the
                explanation is worth reading -- and collapsed when they got it
                right, so a correct answer isn't buried under a wall of text. */}
            <ExplanationPanel text={current.explanation} defaultOpen={!isCorrect} />

            <button onClick={handleNext} className={styles.primaryBtn}>
              {idx + 1 < questions.length ? 'Next question' : 'See results'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
