import React from 'react';
import { Line } from './PassageReader';
import { rangeLabel } from './lines';
import styles from '../styles/Passage.module.css';

/** The lines a question cites, quoted on its review card. */
export default function LineExcerpt({ stimulus, start, end }) {
  const lines = stimulus.lines.filter(l => l.n != null && l.n >= start && l.n <= end);
  if (!lines.length) return null;
  const label = rangeLabel(start, end);
  return (
    <figure className={styles.excerpt}>
      <figcaption className={styles.citedLabel}>
        {label}{stimulus.title ? `, from “${stimulus.title}”` : ''}
      </figcaption>
      <div className={styles.cited}>
        {lines.map((line, i) => <Line key={i} line={line} />)}
      </div>
    </figure>
  );
}
