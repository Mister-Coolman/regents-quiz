import React from 'react';
import { motion } from 'framer-motion';
import styles from '../styles//Chat.module.css';

export default function TypingIndicator() {
  return (
    <motion.div
      className={styles.typing}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <span className={styles.dot} />
      <span className={styles.dot} />
      <span className={styles.dot} />
    </motion.div>
  );
}
