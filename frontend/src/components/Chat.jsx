import { v4 as uuidv4 } from 'uuid';
import React, { useState, useEffect, useRef } from 'react';
import { AnimatePresence, motion }      from 'framer-motion';
import QuizPlayer                       from './QuizPlayer';
import MessageBubble                    from './MessageBubble';
import TypingIndicator                  from './TypingIndicator';
import styles                           from '../styles/Chat.module.css';


export default function Chat() {
  const [sessionId, setSessionId] = useState('');
  useEffect(() => {
    let sid = localStorage.getItem('regentsSessionId');
    if (!sid) {
      sid = uuidv4();
      localStorage.setItem('regentsSessionId', sid);
    }
    setSessionId(sid);
  }, []);
  const [messages, setMessages] = useState([
    { sender: 'bot',     text: 'Hi there! How can I help you today?', questions: [] }
  ]);
  const [input, setInput]                 = useState('');
  const [loading, setLoading]             = useState(false);
  const [activeQuizMsgIdx, setActiveQuizMsgIdx] = useState(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading, activeQuizMsgIdx]);
  useEffect(() => {
    if (!sessionId) return;
     fetch(`/api/history/${sessionId}`)
       .then(res => res.json())
       .then(data => {
         if (Array.isArray(data) && data.length > 0) {
         setMessages(data);
       } else {
         // no prior history → show default greeting
         setMessages([
           { sender: 'bot', text: 'Hi there! How can I help you today?', questions: [] }
         ]);
       }
     })
     .catch(err => {
       console.error('Failed to load history:', err);
       setMessages([
         { sender: 'bot', text: 'Hi there! How can I help you today?', questions: [] }
       ]);
       });
  }, [sessionId]);    
  const sendMessage = async (override = null) => {
    const text = override ?? input.trim();
    if (!text) return;

    // 1) student bubble
    setMessages(ms => [...ms, { sender: 'student', text, questions: [] }]);
    setInput('');
    setLoading(true);

    // 2) typing indicator
    setMessages(ms => [...ms, { id: 'typing', sender: 'bot', typing: true }]);

    try {
      const res  = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text, session_id: sessionId }),
      });
      const data = await res.json();

      // remove typing indicator & add real bot bubble
      setMessages(ms => {
        const withoutTyping = ms.filter(m => m.id !== 'typing');
        return [
          ...withoutTyping,
          {
            sender: 'bot',
            text: data.response,
            questions: data.questions || []
          }
        ];
      });
    } catch {
      setMessages(ms => {
        const withoutTyping = ms.filter(m => m.id !== 'typing');
        return [
          ...withoutTyping,
          { sender: 'bot', text: '❌ Error retrieving questions.', questions: [] }
        ];
      });
    } finally {
      setLoading(false);
    }
  };
  const handleClearHistory = () => {
    // 1) clear local UI state
    setMessages([{ sender: 'bot', text: 'Hi there! How can I help you today?', questions: [] }]);
    setActiveQuizMsgIdx(null);
  
    // 2) reset your session in localStorage
    localStorage.removeItem('regentsSessionId');
  
    // 3) optionally tell the backend to delete session
    fetch('/api/end_session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
  
    // 4) generate a new sessionId
    const newSid = uuidv4();
    localStorage.setItem('regentsSessionId', newSid);
    setSessionId(newSid);
  };
  
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        Algebra I Regents Practice AI Chatbot
        <button
          className={styles.clearHistoryBtn}
          onClick={handleClearHistory}
          title="Clear chat history"
        >
          🗑️
        </button>
      </div>

      <div className={styles.chatWindow}>
        <AnimatePresence initial={false}>
          {messages.map((msg, idx) => (
            msg.typing ? (
              <motion.div
                key="typing"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              >
                <TypingIndicator />
              </motion.div>
            ) : (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
              >
                      <MessageBubble sender={msg.sender}>
                        {msg.sender === 'bot' ? (
                          <div dangerouslySetInnerHTML={{ __html: msg.text }} />
                        ) : (
                          <span>{msg.text}</span>
                        )}

                        {msg.sender === 'bot' && msg.questions?.length > 0 && (
                          <button
                            className={styles.quizButton}
                            onClick={() => setActiveQuizMsgIdx(idx)}
                          >
                            ▶️ Take Interactive Quiz
                          </button>
                        )}
                      </MessageBubble>
              </motion.div>
            )
          ))}
        </AnimatePresence>

        <div ref={messagesEndRef} />
      </div>

      {/* Quiz overlay */}
      {activeQuizMsgIdx !== null && (
        <QuizPlayer
          questions={messages[activeQuizMsgIdx].questions}
          onFinish={() => setActiveQuizMsgIdx(null)}
        />
      )}

      {/* Input bar */}
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
