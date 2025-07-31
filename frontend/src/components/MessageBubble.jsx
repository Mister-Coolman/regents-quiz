// MessageBubble.jsx
import React from 'react';
import styles from '../styles/Chat.module.css';

export default function MessageBubble({ sender, children }) {
  return (
    <div className={`${styles.messageRow} ${styles[sender]}`}>
      {sender === 'bot' && (
        <img src="/bot-avatar.png" alt="Bot" className={styles.avatar} />
      )}
      <div className={`${styles.bubble} ${styles[sender]}`}>
        {children}
      </div>
      {sender === 'student' && (
        <img src="/user-avatar.png" alt="You" className={styles.avatar} />
      )}
    </div>
  );
}