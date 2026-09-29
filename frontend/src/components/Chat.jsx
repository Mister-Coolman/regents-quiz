import { v4 as uuidv4 } from 'uuid';
import React, { useState, useEffect, useRef } from 'react';
import QuizPlayer                       from './QuizPlayer';
import MessageBubble                    from './MessageBubble';
import TypingIndicator                  from './TypingIndicator';
import SubjectMark, { SUBJECTS }        from './SubjectMark';
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
  // loading history replaces the whole list, and React would then match new
  // messages to old ones and reuse the wrong elements.
  const nextKey = useRef(0);
  const withKeys = (list) => list.map(m => ({ ...m, key: m.key ?? `m${nextKey.current++}` }));

  // The greeting is a sentinel for "nothing asked yet": it switches the page to
  // the welcome screen and is never drawn in the transcript. Fixed key so the
  // empty check below can recognise it.
  const greeting = () => ([
    { key: 'greeting', sender: 'bot', text: 'Ask for a practice set, a list of topics, or a question count.', questions: [] }
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
        replaceTyping({ sender: 'bot', text: `${detail} Try again in a moment.`, questions: [], failedQuery: text });
        return;
      }

      const data = await res.json();
      if (!data?.response) {
        replaceTyping({ sender: 'bot', text: 'The server sent back an empty reply. Try again in a moment.', questions: [], failedQuery: text });
        return;
      }

      replaceTyping({ sender: 'bot', text: data.response, questions: data.questions || [] });
    } catch (err) {
      console.error('Query failed:', err);
      replaceTyping({
        sender: 'bot',
        text: "Couldn't reach the server. Check your connection, then try again.",
        questions: [],
        failedQuery: text,
      });
    } finally {
      setLoading(false);
    }
  };
  // "New chat" can be undone for a few seconds, so the old session is only
  // ended on the backend once that window has passed.
  const UNDO_MS = 8000;
  const [cleared, setCleared] = useState(null);   // { sessionId, messages, timer }

  const endSession = (sid) => {
    fetch(`${apiBase}/api/end_session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid })
    }).catch(err => console.error('Failed to end session:', err));
  };

  const handleClearHistory = () => {
    if (cleared) {
      clearTimeout(cleared.timer);
      endSession(cleared.sessionId);
    }
    const oldSid = sessionId;
    const timer = setTimeout(() => {
      endSession(oldSid);
      setCleared(null);
    }, UNDO_MS);
    setCleared({ sessionId: oldSid, messages, timer });

    setMessages(greeting());
    setActiveQuizKey(null);
    const newSid = uuidv4();
    localStorage.setItem('regentsSessionId', newSid);
    setSessionId(newSid);
  };

  const handleUndoClear = () => {
    if (!cleared) return;
    clearTimeout(cleared.timer);
    localStorage.setItem('regentsSessionId', cleared.sessionId);
    setSessionId(cleared.sessionId);
    setMessages(cleared.messages);
    setCleared(null);
  };
  
  // Only the greeting so far: show the welcome screen instead of a lone bubble.
  const isEmpty = messages.length === 1 && messages[0].key === 'greeting';

  return (
    <div className={styles.app}>
      <header className={styles.nav}>
        <div className={styles.navInner}>
          <span className={styles.wordmark}>
            <span className={styles.marks} aria-hidden="true">
              {SUBJECTS.map(s => <SubjectMark key={s.name} subject={s} size={11} />)}
            </span>
            Regents Prep
          </span>
          {!isEmpty && !activeQuiz && (
            <button className={styles.navBtn} onClick={handleClearHistory}>
              New chat
            </button>
          )}
        </div>
      </header>

      {activeQuiz ? (
        <main className={styles.main}>
          <QuizPlayer
            questions={activeQuiz.questions}
            sessionId={sessionId}
            onFinish={() => setActiveQuizKey(null)}
          />
        </main>
      ) : (
        <>
          {/* Keyed by session so clearing history discards the whole subtree. */}
          <main className={styles.main} key={sessionId}>
            {isEmpty ? (
              <section className={styles.welcome}>
                <h1 className={styles.headline}>Practice with real Regents questions.</h1>
                <p className={styles.lede}>
                  Questions and answer keys come from past Regents exams. The
                  explanations and hints are written by AI and can contain mistakes.
                </p>
                <ul className={styles.subjectList}>
                  {SUBJECTS.map(s => (
                    <li key={s.name}>
                      <button
                        className={styles.subjectRow}
                        onClick={() => sendMessage(`List ${s.name} topics`)}
                        disabled={loading}
                      >
                        <SubjectMark subject={s} size={18} />
                        <span className={styles.subjectName}>{s.name}</span>
                        <span className={styles.subjectAction}>See topics</span>
                        <span className={styles.chevron} aria-hidden="true">›</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : (
              <div className={styles.transcript} role="log" aria-live="polite" aria-label="Conversation">
                {messages.filter(m => m.key !== 'greeting').map((msg) => (
                  msg.typing ? (
                    <TypingIndicator key="typing" />
                  ) : (
                    <MessageBubble key={msg.key} sender={msg.sender} isError={Boolean(msg.failedQuery)}>
                      {/* Only replies from /api/query are HTML (built server-side with
                          every dynamic value escaped). Errors carry text from wherever
                          the failure came from, so they are rendered as plain text. */}
                      {msg.sender === 'bot' && !msg.failedQuery ? (
                        <div className={styles.botHtml} dangerouslySetInnerHTML={{ __html: msg.text }} />
                      ) : (
                        msg.text
                      )}

                      {msg.sender === 'bot' && msg.questions?.length > 0 && (
                        <button
                          className={styles.primaryBtn}
                          onClick={() => setActiveQuizKey(msg.key)}
                        >
                          Start quiz
                        </button>
                      )}

                      {msg.failedQuery && (
                        <button
                          className={styles.textBtn}
                          onClick={() => sendMessage(msg.failedQuery)}
                          disabled={loading}
                        >
                          Try again
                        </button>
                      )}
                    </MessageBubble>
                  )
                ))}
              </div>
            )}

            <div ref={messagesEndRef} />
          </main>

          <footer className={styles.composerDock}>
            {/* The live region stays mounted so screen readers catch the change. */}
            <div role="status">
              {cleared && (
                <div className={styles.undoBar}>
                  <span>Chat cleared.</span>
                  <button className={styles.textBtn} onClick={handleUndoClear}>Undo</button>
                </div>
              )}
            </div>
            <form
              className={styles.composer}
              onSubmit={e => { e.preventDefault(); sendMessage(); }}
            >
              <label htmlFor="composer-input" className={styles.composerLabel}>
                Ask for a practice set, a list of topics or a question count
              </label>
              <div className={styles.composerRow}>
                <input
                  id="composer-input"
                  type="text"
                  placeholder="5 Geometry MCQs on circles"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                />
                <button type="submit" className={styles.sendBtn} disabled={loading}>
                  Send
                </button>
              </div>
            </form>
            <button
              className={styles.helpBtn}
              onClick={() => sendMessage('help')}
              disabled={loading}
            >
              See examples
            </button>
          </footer>
        </>
      )}
    </div>
  );
}
