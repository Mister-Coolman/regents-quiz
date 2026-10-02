import React, { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react';
import FootnoteText from './FootnoteText';
import { rangeKey, rangeLabel, refsFor, segment } from './lines';
import styles from '../styles/Passage.module.css';

const BASE_PX = 17;
const MIN_PX = 14;
let measureCanvas = null;

/**
 * The font size (MIN_PX to BASE_PX) at which the longest printed line fits
 * the column, so on most screens every printed line is one row on screen.
 * Below MIN_PX the text would be too small to read; lines wrap instead.
 */
export function useFitFont(ref, lines) {
  const [size, setSize] = useState(BASE_PX);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const fit = () => {
      const text = el.querySelector('[data-line-text]');
      if (!text) return;
      const cs = getComputedStyle(text);
      measureCanvas = measureCanvas || document.createElement('canvas');
      const ctx = measureCanvas.getContext('2d');
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${BASE_PX}px ${cs.fontFamily}`;
      // An indented line starts 1.5em in (.line[data-indent] .text).
      const widest = Math.max(...lines.map(l => ctx.measureText(l.text).width + (l.indent ? 1.5 * BASE_PX : 0)));
      // The first row of a line has the full width (the hanging indent only
      // moves continuations); keep a little back for a cited range's band.
      const room = text.clientWidth - 20;
      if (widest > 0 && room > 0) {
        const fitted = Math.floor((BASE_PX * room / widest) * 4) / 4;
        setSize(Math.max(MIN_PX, Math.min(BASE_PX, fitted)));
      }
    };
    fit();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fit) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [lines]);
  return size;
}

/**
 * One printed line, numbered. Every line carries its number (every fifth
 * larger, as printed on the exam), so a printed line that wraps on a narrow
 * screen is never mistaken for two: the wrapped part has no number and
 * hangs indented.
 */
export function Line({ line, showNumber = true }) {
  const fifth = line.n != null && line.n % 5 === 0;
  return (
    <div
      className={styles.line}
      data-stanza={line.stanza_break ? 'true' : undefined}
      data-indent={line.indent ? 'true' : undefined}
    >
      <span className={styles.num} data-fifth={fifth ? 'true' : undefined} aria-hidden="true">
        {showNumber ? line.n : ''}
      </span>
      <span className={styles.text} data-line-text>
        <FootnoteText text={line.text} notes={line.notes} />
      </span>
    </div>
  );
}

function Passage({ stimulus, refs, rangeRefs, questionNumber, onBackToQuestion }) {
  const headingId = `passage-${stimulus.id}-title`;
  const linesRef = useRef(null);
  const fontSize = useFitFont(linesRef, stimulus.lines);
  return (
    <article className={styles.passage} aria-labelledby={headingId}>
      <header className={styles.passageHeader}>
        <p className={styles.passageLabel}>Passage {stimulus.label}</p>
        <h3 id={headingId} className={styles.title}>
          {stimulus.title
            ? <FootnoteText text={stimulus.title} notes={stimulus.title_notes} />
            : `Passage ${stimulus.label}`}
        </h3>
        {stimulus.author && <p className={styles.author}>by {stimulus.author}</p>}
      </header>
      {stimulus.intro && (
        <p className={styles.intro}>
          <FootnoteText text={stimulus.intro} notes={stimulus.intro_notes} />
        </p>
      )}

      <div className={styles.lines} ref={linesRef} style={{ fontSize, '--fs': `${fontSize}px` }}>
        {segment(stimulus.lines, refs).map((seg, i) => {
          if (!seg.ref) {
            return seg.lines.map((line, j) => <Line key={`${i}-${j}`} line={line} />);
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
              {seg.lines.map((line, j) => <Line key={j} line={line} />)}
            </div>
          );
        })}
      </div>

      {stimulus.footnotes?.length > 0 && (
        <ul className={styles.footnotes} aria-label="Footnotes">
          {stimulus.footnotes.map((f, i) => {
            // Stored as printed: "2 transient: passing or temporary".
            const m = f.match(/^(\d+)\s+([\s\S]*)$/);
            return (
              <li key={i}>
                {m ? <><sup className={styles.mark}><span className="sr-only">footnote </span>{m[1]}</sup>{m[2]}</> : f}
              </li>
            );
          })}
        </ul>
      )}
      {stimulus.credit && <p className={styles.credit}>{stimulus.credit}</p>}
    </article>
  );
}

/**
 * The passages of a set, line by line as printed: every line numbered (every
 * fifth larger), text sized to fit the column, and the lines the current question cites banded, bracketed and
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
