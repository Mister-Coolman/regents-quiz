import React, { useState, useEffect, useRef } from 'react';
import MathText from './MathText';
import SubjectMark, { subjectLabel } from './SubjectMark';
import ScoreDial from './ScoreDial';
import PassageReader from './PassageReader';
import LineExcerpt from './LineExcerpt';
import { rangeLabel } from './lines';
import styles from '../styles/QuizPlayer.module.css';
import passageStyles from '../styles/Passage.module.css';

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

/** "7 min 12 s", or "45 s" under a minute. */
function formatDuration(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const sec = total % 60;
  return m > 0 ? `${m} min ${sec} s` : `${sec} s`;
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

export default function QuizPlayer({ questions = [], stimuli = [], sessionId, onFinish }) {
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
  // What /api/check released for each answered question:
  // { [questionId]: { correct, correct_answer, explanation } }. Answers are not
  // sent with the questions, so this is the only place they exist client-side,
  // and only for questions already attempted.
  const [revealed, setRevealed]     = useState(saved?.revealed ?? {});
  const [showAnswer, setShowAnswer] = useState(false);
  const [checking, setChecking]     = useState(false);
  const [finished, setFinished]     = useState(saved?.finished ?? false);
  // How many hints the student has unlocked on the current question.
  const [hintLevel, setHintLevel]   = useState(0);
  // Shown when "Check answer" can't go ahead -- nothing chosen yet, or the
  // check request failed. The button stays enabled so it can explain itself
  // instead of sitting greyed out.
  const [nudge, setNudge]           = useState('');
  const [hintsUsed, setHintsUsed]   = useState(saved?.hintsUsed ?? 0);
  // Captured once at mount: true only when this run picked up stored progress,
  // rather than simply having advanced past the first question.
  const [wasResumed, setWasResumed] = useState(() => Object.keys(saved?.results ?? {}).length > 0);

  // A passage set: the reader sits beside (or above) the questions.
  const isSet = Array.isArray(stimuli) && stimuli.length > 0;
  const readerRef = useRef(null);
  const questionRef = useRef(null);
  // What a screen reader hears when the question changes.
  const [announcement, setAnnouncement] = useState('');

  // Time spent with the quiz open, counted up and shown only on the results
  // screen of a passage set. Time with the quiz closed doesn't count.
  const elapsedBase = useRef(saved?.elapsedMs ?? 0);
  const openedAt = useRef(Date.now());
  const elapsedNow = () => elapsedBase.current + (Date.now() - openedAt.current);
  const [finishedMs, setFinishedMs] = useState(saved?.finishedMs ?? null);

  useEffect(() => {
    saveProgress(storageKey, {
      idx, results, revealed, hintsUsed, finished,
      elapsedMs: finished ? finishedMs : elapsedNow(), finishedMs,
    });
  }, [storageKey, idx, results, revealed, hintsUsed, finished, finishedMs]);

  const current = questions[idx];
  const { subject = '', month = '', year = '', question_no: questionNo } = current;
  const stimulusById = Object.fromEntries((stimuli || []).map(st => [st.id, st]));
  // Constructed-response questions come back ungraded (correct: null) -- they
  // are marked with a rubric -- so they count toward neither score nor misses.
  const graded = questions.filter(q => typeof results[q.id] === 'boolean');
  const score = graded.filter(q => results[q.id]).length;
  const missed = questions.filter(q => results[q.id] === false);
  const currentReveal = revealed[current.id];
  const isCorrect = currentReveal?.correct === true;

  const hints = current.hints ?? [];
  const shownHints = hints.slice(0, hintLevel);
  const hintsLeft = hints.length - hintLevel;

  // Check user's answer
  const handleCheck = async () => {
    if (checking) return;
    if (selected === null || selected === '') {
      setNudge(current.type === 'MCQ' ? 'Choose an answer first.' : 'Type an answer first.');
      return;
    }
    setNudge('');
    setChecking(true);
    try {
      const res = await fetch(`${apiBase}/api/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, question_id: current.id, answer: String(selected) }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body) {
        setNudge(body?.error || "Couldn't check your answer. Check your connection, then try again.");
        return;
      }
      setRevealed(r => ({ ...r, [current.id]: body }));
      setResults(r => ({ ...r, [current.id]: body.correct }));
      setShowAnswer(true);
    } catch {
      setNudge("Couldn't check your answer. Check your connection, then try again.");
    } finally {
      setChecking(false);
    }
  };

  const handleRestart = () => {
    clearProgress(storageKey);
    setIdx(0);
    setSel(null);
    setResults({});
    setRevealed({});
    setShowAnswer(false);
    setFinished(false);
    setHintLevel(0);
    setHintsUsed(0);
    setWasResumed(false);
    elapsedBase.current = 0;
    openedAt.current = Date.now();
    setFinishedMs(null);
  };

  const focusQuestion = () => {
    questionRef.current?.focus({ preventScroll: true });
    questionRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };

  // Next question or finish
  const handleNext = () => {
    setShowAnswer(false);
    setNudge('');
    setSel(null);
    setHintLevel(0);
    if (idx + 1 < questions.length) {
      setIdx(i => i + 1);
      if (isSet) {
        setAnnouncement(`Question ${idx + 2} of ${questions.length}`);
        // In one column the passage sits above the question: bring the next
        // question up rather than leaving the student at the old feedback.
        if (window.matchMedia?.('(max-width: 1023px)').matches) {
          requestAnimationFrame(() => questionRef.current?.scrollIntoView({ block: 'start' }));
        }
      }
    } else {
      setFinishedMs(elapsedNow());
      setFinished(true);
    }
  };

  if (finished) {
    const perfect = graded.length > 0 && score === graded.length;
    return (
      <div className={styles.quiz}>
        <div className={styles.topbar}>
          <button onClick={onFinish} className={styles.backBtn}>
            <span aria-hidden="true">‹</span> Chat
          </button>
        </div>

        <section className={styles.results}>
          {graded.length > 0 && (
            <ScoreDial
              results={graded.map(q => results[q.id])}
              score={score}
              total={graded.length}
            />
          )}
          <h2 className={styles.resultsHeadline}>
            {graded.length === 0
              ? 'Quiz finished.'
              : perfect
                ? 'Every question right.'
                : `${missed.length} to review.`}
          </h2>
          {graded.length < questions.length && (
            <p className={styles.resultsNote}>
              {questions.length - graded.length === 1
                ? '1 written-response question is marked with a rubric, so it isn’t scored here.'
                : `${questions.length - graded.length} written-response questions are marked with a rubric, so they aren’t scored here.`}
            </p>
          )}
          <p className={styles.resultsNote}>
            {hintsUsed === 0
              ? 'No hints used.'
              : `${hintsUsed} hint${hintsUsed === 1 ? '' : 's'} used.`}
            {isSet && finishedMs != null && <> Time: {formatDuration(finishedMs)}.</>}
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
                  <span className={styles.reviewNumber}>
                    Question {isSet && q.question_no ? q.question_no : questions.indexOf(q) + 1}
                  </span>
                  <span>{q.topic}</span>
                  <span className={styles.reviewAnswer}>Answer: {revealed[q.id]?.correct_answer}</span>
                </div>
                {(q.line_refs || []).map(r => stimulusById[r.stimulus_id] && (
                  <LineExcerpt
                    key={`${r.stimulus_id}-${r.start}`}
                    stimulus={stimulusById[r.stimulus_id]}
                    start={r.start}
                    end={r.end}
                  />
                ))}
                {q.question_image_path && (
                  <img
                    className={styles.reviewImage}
                    src={`${apiBase}/${q.question_image_path}`}
                    alt={q.alt_text || `Diagram for question ${questions.indexOf(q) + 1}`}
                  />
                )}
                {q.question_text && <p className={styles.reviewQuestion}>{q.question_text}</p>}
                <ExplanationPanel text={revealed[q.id]?.explanation} />
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
    if (String(num) === String(currentReveal?.correct_answer)) return styles.bubbleCorrect;
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
          <span>
            {[subjectLabel(subject), [month, year].filter(Boolean).join(' '), questionNo && `question ${questionNo}`]
              .filter(Boolean).join(', ')}
          </span>
        </div>
      </div>

      {isSet && <p role="status" className="sr-only">{announcement}</p>}

      {isSet ? (
        <div className={passageStyles.layout}>
          <PassageReader
            ref={readerRef}
            stimuli={stimuli}
            question={current}
            questionNumber={questionNo || idx + 1}
            questionTargetId="question-card"
            onBackToQuestion={focusQuestion}
          />
          <div>{questionBlock()}</div>
        </div>
      ) : questionBlock()}
    </div>
  );

  function questionBlock() {
    return (
    <>
      <div className={styles.counter}>
        <h2 className="sr-only">Question {idx + 1} of {questions.length}</h2>
        <span className={styles.counterNum} aria-hidden="true">{idx + 1}</span>
        <span className={styles.counterOf} aria-hidden="true">of {questions.length}</span>
        {wasResumed && <span className={styles.resumed}>Picked up where you left off</span>}
      </div>

      <div className={styles.card} id="question-card" ref={questionRef} tabIndex={-1}>
        {current.question_image_path && (
          <img
            className={isSet ? `${styles.questionImage} ${styles.questionCrop}` : styles.questionImage}
            src={`${apiBase}/${current.question_image_path}`}
            alt={current.alt_text || 'Diagram for this question'}
          />
        )}

        {isSet && (current.line_refs || []).length > 0 && (
          <div className={styles.rereadRow}>
            {current.line_refs.map(r => (
              <button
                key={`${r.stimulus_id}-${r.start}`}
                type="button"
                className={styles.textBtn}
                onClick={() => readerRef.current?.focusRange(r)}
              >
                Reread {rangeLabel(r.start, r.end).toLowerCase()}
              </button>
            ))}
          </div>
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
                  onChange={() => { setSel(num); setNudge(''); }}
                  disabled={showAnswer}
                  className={styles.bubbleInput}
                />
                <span aria-hidden="true">{num}</span>
                <span className="sr-only">
                  Choice {num}
                  {showAnswer && String(num) === String(currentReveal?.correct_answer) ? ', correct answer' : ''}
                  {showAnswer && selected === num && String(num) !== String(currentReveal?.correct_answer) ? ', your answer' : ''}
                </span>
              </label>
            ))}
          </fieldset>
        ) : (
          <input
            type="text"
            value={selected || ''}
            onChange={e => { setSel(e.target.value); setNudge(''); }}
            placeholder="Type your answer"
            aria-label="Your answer"
            disabled={showAnswer}
            className={styles.freeResponseInput}
          />
        )}

        {!showAnswer ? (
          <>
            <div className={styles.checkRow}>
              <button onClick={handleCheck} className={styles.primaryBtn} aria-busy={checking}>
                {checking ? 'Checking…' : 'Check answer'}
              </button>
              <p className={styles.nudge} role="alert">{nudge}</p>
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
            <p
              className={currentReveal?.correct === null ? styles.ungradedMsg
                : isCorrect ? styles.correctMsg : styles.incorrectMsg}
              role="status"
            >
              {currentReveal?.correct === null
                ? 'This one is marked with a rubric. Compare your work with the explanation.'
                : isCorrect
                  ? 'Correct.'
                  : <>Not quite. The answer is <strong>{currentReveal?.correct_answer}</strong>.</>}
            </p>

            {/* Opened by default when they got it wrong -- that's the moment the
                explanation is worth reading -- and collapsed when they got it
                right, so a correct answer isn't buried under a wall of text. */}
            <ExplanationPanel text={currentReveal?.explanation} defaultOpen={!isCorrect} />

            <button onClick={handleNext} className={styles.primaryBtn}>
              {idx + 1 < questions.length ? 'Next question' : 'See results'}
            </button>
          </div>
        )}
      </div>
    </>
    );
  }
}
