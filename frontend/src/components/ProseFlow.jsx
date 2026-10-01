import React, { useLayoutEffect, useRef, useState } from 'react';
import { rangeKey, rangeLabel } from './lines';
import styles from '../styles/Passage.module.css';

/** Printed lines grouped into paragraphs: a new one at each indented first
 *  line or section break. */
function paragraphs(lines) {
  const out = [];
  lines.forEach((line, i) => {
    if (i === 0 || line.indent || line.stanza_break) {
      out.push({ indent: Boolean(line.indent), gap: i > 0 && Boolean(line.stanza_break), lines: [] });
    }
    out[out.length - 1].lines.push(line);
  });
  return out;
}

// A printed line ending in a hyphen or dash runs straight into the next.
const joiner = text => (/[-–—]$/.test(text) ? '' : ' ');

/**
 * Prose as paragraphs that wrap to the screen, the way a reader expects,
 * while keeping the exam's line numbers usable: every fifth number sits in
 * the margin beside the word that starts that printed line, and each cited
 * range keeps its band, a text label and an ink bracket in the margin.
 *
 * Poems don't use this: their printed line breaks are part of the poem.
 */
export default function ProseFlow({
  lines, refs = [], stimulusId, questionNumber, rangeRefs, onBackToQuestion, numberEvery = 5, firstNumbered,
}) {
  const containerRef = useRef(null);
  const [bars, setBars] = useState([]);
  const refsKey = refs.map(r => `${r.start}-${r.end}`).join(',');

  // The bracket spans the cited text however it wrapped, so it is measured
  // after layout and again whenever the column changes width.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el || !refs.length) { setBars([]); return undefined; }
    const measure = () => {
      const base = el.getBoundingClientRect();
      const groups = {};
      el.querySelectorAll('[data-ref]').forEach(span => {
        for (const r of span.getClientRects()) {
          const g = groups[span.dataset.ref] || (groups[span.dataset.ref] = { top: Infinity, bottom: -Infinity });
          g.top = Math.min(g.top, r.top - base.top);
          g.bottom = Math.max(g.bottom, r.bottom - base.top);
        }
      });
      setBars(Object.entries(groups).map(([key, g]) => ({ key, top: g.top, height: g.bottom - g.top })));
    };
    measure();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [lines, refsKey]);

  const refFor = n => (n == null ? null : refs.find(r => n >= r.start && n <= r.end));

  return (
    <div className={styles.flow} ref={containerRef}>
      {bars.map(b => (
        <span key={b.key} className={styles.flowBar} style={{ top: b.top, height: b.height }} aria-hidden="true" />
      ))}
      {paragraphs(lines).map((para, p) => (
        <p
          key={p}
          className={styles.para}
          data-indent={para.indent ? 'true' : undefined}
          data-gap={para.gap ? 'true' : undefined}
        >
          {para.lines.map((line, j) => {
            const text = line.text.trim();
            const [, first = '', rest = ''] = text.match(/^(\S*)([\s\S]*)$/) || [];
            const ref = refFor(line.n);
            const startsRef = ref && line.n === ref.start;
            const showNumber = line.n != null
              && (line.n % numberEvery === 0 || line.n === firstNumbered || startsRef);
            const isLast = j === para.lines.length - 1;
            const label = ref && rangeLabel(ref.start, ref.end);
            return (
              <span
                key={j}
                className={ref ? styles.flowCited : undefined}
                data-ref={ref ? `${ref.start}-${ref.end}` : undefined}
              >
                {/* Number, label and first word can't be split by a wrap, so
                    the margin number lands on the line where its printed line
                    begins. */}
                <span className={styles.flowStart}>
                  {showNumber && <span className={styles.flowNum} aria-hidden="true">{line.n}</span>}
                  {startsRef && (
                    <span
                      className={styles.flowLabel}
                      tabIndex={-1}
                      ref={el => { if (rangeRefs) rangeRefs.current[rangeKey(stimulusId, ref.start)] = el; }}
                    >
                      {label}
                      <span className="sr-only">, cited in question {questionNumber}</span>
                    </span>
                  )}
                  {first}
                </span>
                {rest}
                {isLast ? '' : joiner(text)}
                {ref && line.n === ref.end && onBackToQuestion && (
                  <button type="button" className={`${styles.backLink} ${styles.flowBack}`} onClick={onBackToQuestion}>
                    Back to the question
                  </button>
                )}
              </span>
            );
          })}
        </p>
      ))}
    </div>
  );
}
