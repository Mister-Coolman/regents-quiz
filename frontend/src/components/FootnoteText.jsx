import React from 'react';
import styles from '../styles/Passage.module.css';

/**
 * Text with its footnote markers drawn where they were printed. `notes` are
 * {n, at}: the footnote number and a character offset into `text`.
 */
export default function FootnoteText({ text = '', notes }) {
  if (!notes?.length) return text;
  const parts = [];
  let last = 0;
  [...notes].sort((a, b) => a.at - b.at).forEach((note, i) => {
    parts.push(text.slice(last, note.at));
    parts.push(
      <sup key={i} className={styles.mark}>
        <span className="sr-only">footnote </span>{note.n}
      </sup>,
    );
    last = note.at;
  });
  parts.push(text.slice(last));
  return parts;
}
