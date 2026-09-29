import React from 'react';
import styles from '../styles/QuizPlayer.module.css';

const SIZE = 240;
const C = SIZE / 2;
const OUTER = 108;       // outer end of every tick
const LONG = 26;         // a correct answer: a full capsule, like an hour marker
const SHORT = 10;        // a miss: a minute tick
const SWEEP_MS = 700;    // time for the ticks to fill in, clockwise from the top

/**
 * A clock face with one tick per question, read clockwise from twelve.
 * Correct answers are bold hour markers; misses stay as fine minute ticks.
 */
export default function ScoreDial({ results, score, total }) {
  const n = results.length;
  // Keep capsules from touching on long quizzes.
  const stroke = Math.max(2, Math.min(7, (2 * Math.PI * (OUTER - LONG)) / n * 0.45));

  return (
    <div className={styles.dial}>
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`${score} of ${total} correct`}
      >
        <circle cx={C} cy={C} r={C - 1} className={styles.dialFace} />
        {results.map((ok, i) => {
          const a = (i / n) * 2 * Math.PI - Math.PI / 2;
          const len = ok ? LONG : SHORT;
          const x1 = C + Math.cos(a) * (OUTER - len);
          const y1 = C + Math.sin(a) * (OUTER - len);
          const x2 = C + Math.cos(a) * OUTER;
          const y2 = C + Math.sin(a) * OUTER;
          return (
            <line
              key={i}
              x1={x1} y1={y1} x2={x2} y2={y2}
              strokeWidth={ok ? stroke : 2}
              strokeLinecap="round"
              className={ok ? styles.tickRight : styles.tickMiss}
              style={{ animationDelay: `${(i / n) * SWEEP_MS}ms` }}
            />
          );
        })}
      </svg>
      <div className={styles.dialCenter} aria-hidden="true">
        <span className={styles.dialScore}>{score}</span>
        <span className={styles.dialTotal}>of {total}</span>
      </div>
    </div>
  );
}
