import { v4 as uuidv4 } from 'uuid';
import React, { useState, useEffect, useRef } from 'react';
import { AnimatePresence, motion }      from 'framer-motion';
import QuizPlayer                       from './QuizPlayer';
import MessageBubble                    from './MessageBubble';
import TypingIndicator                  from './TypingIndicator';
import styles                           from '../styles/Chat.module.css';

const apiBase = import.meta.env.VITE_API_BASE_URL || '';

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
  // Messages carry a stable key of their own. Array indices can't be used:
  // loading history replaces the whole list, and AnimatePresence would then
  // match new bubbles to old ones and animate/render the wrong entries.
  const nextKey = useRef(0);
  const withKeys = (list) => list.map(m => ({ ...m, key: m.key ?? `m${nextKey.current++}` }));

  // Fixed key: clearing history sets the greeting, then the history effect sets
  // it again. With a freshly minted key each time React would unmount and
  // remount the bubble, and framer-motion strands the orphaned node.
  const greeting = () => ([
    { key: 'greeting', sender: 'bot', text: 'Hi there! How can I help you today?', questions: [] }
  ]);

  const [messages, setMessages] = useState(greeting);
  const [input, setInput]                 = useState('');
  const [loading, setLoading]             = useState(false);
  // Tracked by message key, not array index: the index would silently point at
  // a different message if the list were replaced while the quiz is open.
  const [activeQuizKey, setActiveQuizKey] = useState(null);
  const activeQuiz = messages.find(m => m.key === activeQuizKey) || null;
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading, activeQuizKey]);

  useEffect(() => {
    if (!sessionId) return;
    // Clearing history swaps in a new session id while the previous session's
    // request may still be in flight. Without this guard that stale response
    // lands last and restores the messages the student just cleared.
    let cancelled = false;

    fetch(`${apiBase}/api/history/${sessionId}`)
      .then(res => (res.ok ? res.json() : []))
      .then(data => {
        if (cancelled) return;
        setMessages(Array.isArray(data) && data.length > 0 ? withKeys(data) : greeting());
      })
      .catch(err => {
        if (cancelled) return;
        console.error('Failed to load history:', err);
        setMessages(greeting());
      });

    return () => { cancelled = true; };
  }, [sessionId]);
  const sendMessage = async (override = null) => {
    // Guard here as well as on the buttons: pressing Enter would otherwise
    // fire concurrent requests that race each other into the message list.
    if (loading) return;
    const text = override ?? input.trim();
    if (!text) return;

    setMessages(ms => [
      ...ms,
      ...withKeys([{ sender: 'student', text, questions: [] }]),
      { id: 'typing', key: 'typing', sender: 'bot', typing: true },
    ]);
    setInput('');
    setLoading(true);

    const replaceTyping = (bubble) =>
      setMessages(ms => [...ms.filter(m => m.id !== 'typing'), ...withKeys([bubble])]);

    try {
      const res = await fetch(`${apiBase}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text, session_id: sessionId }),
      });

      // A non-2xx response still carries JSON, but with `error` instead of
      // `response`. Without this check the bot bubble renders as undefined --
      // a blank message that gives the student no idea anything went wrong.
      if (!res.ok) {
        let detail = `The server returned an error (${res.status}).`;
        try {
          const body = await res.json();
          if (body?.error) detail = body.error;
        } catch { /* response wasn't JSON */ }
        replaceTyping({ sender: 'bot', text: `⚠️ ${detail} Please try again.`, questions: [], failedQuery: text });
        return;
      }

      const data = await res.json();
      if (!data?.response) {
        replaceTyping({ sender: 'bot', text: '⚠️ Got an empty reply from the server. Please try again.', questions: [], failedQuery: text });
        return;
      }

      replaceTyping({ sender: 'bot', text: data.response, questions: data.questions || [] });
    } catch (err) {
      console.error('Query failed:', err);
      replaceTyping({
        sender: 'bot',
        text: "⚠️ Couldn't reach the server. Check your connection and try again.",
        questions: [],
        failedQuery: text,
      });
    } finally {
      setLoading(false);
    }
  };
  const handleClearHistory = () => {
    setMessages(greeting());
    setActiveQuizKey(null);

    // Tell the backend to drop the old session, then move to a fresh id.
    // Fire-and-forget is fine -- the new id is what everything uses from here.
    fetch(`${apiBase}/api/end_session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    }).catch(err => console.error('Failed to end session:', err));

    const newSid = uuidv4();
    localStorage.setItem('regentsSessionId', newSid);
    setSessionId(newSid);
  };
  
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.eyebrow}>NY Regents Prep</span>
        <div className={styles.title}>Math Practice Chatbot</div>
        <button
          className={styles.clearHistoryBtn}
          onClick={handleClearHistory}
          title="Clear chat history"
        >
          🗑️
        </button>
      </div>

      {/* Keyed by session so clearing history discards the whole subtree.
          Replacing the list wholesale otherwise leaves framer-motion holding
          exited nodes that never unmount -- invisible, but still taking up
          layout space in the scroll area. */}
      <div className={styles.chatWindow} key={sessionId}>
        <AnimatePresence initial={false}>
          {messages.map((msg) => (
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
                key={msg.key}
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
                      onClick={() => setActiveQuizKey(msg.key)}
                    >
                      ▶️ Take Interactive Quiz
                    </button>
                  )}

                  {msg.failedQuery && (
                    <button
                      className={styles.quizButton}
                      onClick={() => sendMessage(msg.failedQuery)}
                      disabled={loading}
                    >
                      ↻ Try again
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
      {activeQuiz && (
        <QuizPlayer
          questions={activeQuiz.questions}
          onFinish={() => setActiveQuizKey(null)}
        />
      )}

      {/* Input bar */}
      {!activeQuiz && (
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
