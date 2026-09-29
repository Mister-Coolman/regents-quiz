import React from 'react';
import styles from '../styles/Chat.module.css';

// A student's message is shown as the request it is -- a line of text heading
// the reply -- rather than as a text-message bubble.
export default function MessageBubble({ sender, isError = false, children }) {
  if (sender === 'student') {
    return (
      <p className={styles.request}>
        <span className="sr-only">You asked: </span>
        {children}
      </p>
    );
  }
  return (
    <div className={styles.reply} role={isError ? 'alert' : undefined}>
      {children}
    </div>
  );
}
