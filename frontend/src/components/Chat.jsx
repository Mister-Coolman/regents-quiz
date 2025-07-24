import React, { useState, useEffect, useRef } from 'react';
import QuizPlayer from './QuizPlayer';
import styles from '../styles/Chat.module.css';

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      sender: 'bot',
      text: 'Hi there! How can I help you today?',
      questions: []
    }
  ]);
  const [input, setInput]                 = useState('');
  const [loading, setLoading]             = useState(false);
  const [activeQuizMsgIdx, setActiveQuizMsgIdx] = useState(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, activeQuizMsgIdx]);

  const sendMessage = async (override = null) => {
    const text = override ?? input.trim();
    if (!text) return;

    setMessages(m => [...m, { sender: 'student', text }]);
    setInput('');
    setLoading(true);

    try {
      const res  = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text })
      });
      const data = await res.json();
      setMessages(m => [
        ...m,
        {
          sender: 'bot',
          text: data.response,
          questions: data.questions || []
        }
      ]);
    } catch {
      setMessages(m => [
        ...m,
        { sender: 'bot', text: '❌ Error retrieving questions.', questions: [] }
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>Algebra I Regents Practice AI Chatbot</div>

      <div className={styles.chatWindow}>
        {messages.map((msg, idx) => (
          <React.Fragment key={idx}>
            {msg.sender === 'bot' && (
              <div className={`${styles.message} ${styles.bot}`}>
                <div dangerouslySetInnerHTML={{ __html: msg.text }} />
                {msg.questions?.length > 0 && (
                  <button
                    className={styles.quizButton}
                    onClick={() => setActiveQuizMsgIdx(idx)}
                  >
                    ▶️ Take Interactive Quiz
                  </button>
                )}
              </div>
            )}
            {msg.sender === 'student' && (
              <div className={`${styles.message} ${styles.student}`}>
                {msg.text}
              </div>
            )}
          </React.Fragment>
        ))}

        <div ref={messagesEndRef} />
        {loading && <div style={{ textAlign: 'center', color: '#666' }}>Loading…</div>}
      </div>

      {activeQuizMsgIdx !== null && (
        <QuizPlayer
          questions={messages[activeQuizMsgIdx].questions}
          onFinish={() => setActiveQuizMsgIdx(null)}
        />
      )}

      {activeQuizMsgIdx === null && (
        <div className={styles.inputBar}>
          <input
            type="text"
            placeholder="e.g., 5 MCQs on interpreting functions"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendMessage()}
          />
          <div className={styles.actions}>
            <button
              className={styles.sendBtn}
              onClick={() => sendMessage()}
              disabled={loading}
            >
              Send
            </button>
            <button
              className={styles.helpBtn}
              onClick={() => sendMessage('help')}
              disabled={loading}
            >
              Help
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
