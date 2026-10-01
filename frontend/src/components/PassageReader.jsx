import React, { forwardRef, useImperativeHandle, useRef } from 'react';
import { rangeKey, rangeLabel, refsFor, segment } from './lines';
import styles from '../styles/Passage.module.css';

/** One printed line: the number in the gutter, the text with a hanging indent. */
export function Line({ line, showNumber }) {
  return (
    <div className={styles.line} data-stanza={line.stanza_break ? 'true' : undefined}>
      <span className={styles.num} aria-hidden="true">{showNumber ? line.n : ''}</span>
      <span className={styles.text}>{line.text}</span>
    </div>
  );
}

function Passage({ stimulus, refs, rangeRefs, questionNumber, onBackToQuestion }) {
  const headingId = `passage-${stimulus.id}-title`;
  return (
    <article className={styles.passage} aria-labelledby={headingId}>
      <header className={styles.passageHeader}>
        <p className={styles.passageLabel}>Passage {stimulus.label}</p>
        <h3 id={headingId} className={styles.title}>{stimulus.title || `Passage ${stimulus.label}`}</h3>
        {stimulus.author && <p className={styles.author}>by {stimulus.author}</p>}
      </header>
      {stimulus.intro && <p className={styles.intro}>{stimulus.intro}</p>}

      <div className={styles.lines}>
        {segment(stimulus.lines, refs).map((seg, i) => {
          if (!seg.ref) {
            return seg.lines.map((line, j) => (
              <Line key={`${i}-${j}`} line={line} showNumber={line.n != null && line.n % 5 === 0} />
            ));
          }
          const label = rangeLabel(seg.ref.start, seg.ref.end);
          return (
            <div
              key={`${i}-cited`}
              className={styles.cited}
              tabIndex={-1}
              ref={el => { rangeRefs.current[rangeKey(stimulus.id, seg.ref.start)] = el; }}
              role="group"
              aria-label={`${label}, cited in question ${questionNumber}`}
            >
              <p className={styles.citedLabel}>
                {label}, cited in question {questionNumber}
                <button type="button" className={styles.backLink} onClick={onBackToQuestion}>
                  Back to the question
                </button>
              </p>
              {seg.lines.map((line, j) => <Line key={j} line={line} showNumber />)}
            </div>
          );
        })}
      </div>

      {stimulus.footnotes?.length > 0 && (
        <ol className={styles.footnotes} aria-label="Footnotes">
          {stimulus.footnotes.map((f, i) => <li key={i}>{f}</li>)}
        </ol>
      )}
      {stimulus.credit && <p className={styles.credit}>{stimulus.credit}</p>}
    </article>
  );
}

/**
 * The passages of a set, as printed: line breaks kept, every fifth line
 * numbered, and the lines the current question cites banded, bracketed and
 * labelled. focusRange() moves keyboard and screen reader focus to a range.
 */
const PassageReader = forwardRef(function PassageReader(
  { stimuli, question, questionNumber, questionTargetId, onBackToQuestion }, ref,
) {
  const rangeRefs = useRef({});

  useImperativeHandle(ref, () => ({
    focusRange(r) {
      const el = rangeRefs.current[rangeKey(r.stimulus_id, r.start)];
      if (!el) return;
      el.focus({ preventScroll: true });
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    },
  }), []);

  return (
    <section className={styles.reader} aria-label={stimuli.length === 1 ? 'Passage' : 'Passages'}>
      <a href={`#${questionTargetId}`} className={styles.skip}>Skip to the question</a>
      {stimuli.map(s => (
        <Passage
          key={s.id}
          stimulus={s}
          refs={refsFor(question, s.id)}
          rangeRefs={rangeRefs}
          questionNumber={questionNumber}
          onBackToQuestion={onBackToQuestion}
        />
      ))}
    </section>
  );
});

export default PassageReader;
