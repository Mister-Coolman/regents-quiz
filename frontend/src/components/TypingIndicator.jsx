import React from 'react';
import styles from '../styles/Chat.module.css';

// The wait is a real model call, so say what is happening instead of
// imitating someone typing.
export default function TypingIndicator() {
  return (
    <p className={styles.pending} role="status">
      Finding questions…
    </p>
  );
}
