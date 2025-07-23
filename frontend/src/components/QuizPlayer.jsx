import React, { useState } from 'react';

export default function QuizPlayer({ questions = [], onFinish }) {
  if (!Array.isArray(questions) || questions.length === 0) {
    return (
      <div style={{ padding: '1rem', textAlign: 'center' }}>
        <strong>Loading quiz…</strong>
      </div>
    );
  }

  const [idx, setIdx]               = useState(0);
  const [selected, setSel]          = useState(null);
  const [score, setScore]           = useState(0);
  const [missed, setMissed]         = useState([]);
  const [showAnswer, setShowAnswer] = useState(false);
  const [isCorrect, setIsCorrect]   = useState(false);

  const current = questions[idx];
  const { subject = '', month = '', year = '' } = current;

  const handleCheck = () => {
    const correct = String(selected) === String(current.correct_answer);
    setIsCorrect(correct);
    if (correct) setScore(s => s + 1);
    else setMissed(m => [...m, current.id]);
    setShowAnswer(true);
  };

  const handleNext = () => {
    setShowAnswer(false);
    setSel(null);
    if (idx + 1 < questions.length) {
      setIdx(i => i + 1);
    } else {
      alert(`Quiz complete! Your score: ${score}/${questions.length}`);
      onFinish();
    }
  };

  return (
    <div style={{
      position: 'relative',
      padding: 16,
      background: '#fafafa',
      borderRadius: 8,
      boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
      maxWidth: 600,
      margin: '0 auto'
    }}>
      {/* ✖️ Close button */}
      <button
        onClick={onFinish}
        aria-label="Close quiz"
        style={{
          position: 'absolute',
          top: 8,
          right: 8,
          border: 'none',
          background: 'transparent',
          fontSize: '1.5rem',
          lineHeight: 1,
          cursor: 'pointer',
        }}
      >
        &times;
      </button>

      {/* Combined header row */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginBottom: 12
      }}>
        <h2 style={{ margin: 0 }}>
          Question {idx + 1} of {questions.length}
        </h2>
        <div style={{ fontSize: '0.9rem', color: '#555' }}>
          {subject} – {month} {year}
        </div>
      </div>

      {/* Question image */}
      {current.question_image_path && (
        <img
          src={`${current.question_image_path}`}
          alt="Question diagram"
          style={{
            width: '100%',
            maxHeight: 300,
            objectFit: 'contain',
            marginBottom: 16
          }}
        />
      )}

      {/* Question text */}
      <p style={{ marginBottom: 16 }}>{current.question_text}</p>

      {!showAnswer ? (
        <>
          {/* MCQ options 1–4 */}
          {current.type === 'MCQ' && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
              {[1, 2, 3, 4].map(num => (
                <button
                  key={num}
                  onClick={() => setSel(num)}
                  style={{
                    flex: 1,
                    margin: '0 4px',
                    padding: '0.75rem',
                    fontSize: '1.2rem',
                    borderRadius: '6px',
                    border: selected === num ? '2px solid #007bff' : '1px solid #ccc',
                    background: selected === num ? '#e7f1ff' : 'white',
                    cursor: 'pointer'
                  }}
                >
                  {num}
                </button>
              ))}
            </div>
          )}

          {/* Free-response if not MCQ */}
          {current.type !== 'MCQ' && (
            <input
              type="text"
              value={selected || ''}
              onChange={e => setSel(e.target.value)}
              placeholder="Type your answer"
              style={{
                width: '100%',
                padding: 8,
                marginBottom: 16,
                borderRadius: 4,
                border: '1px solid #ccc'
              }}
            />
          )}

          <button
            onClick={handleCheck}
            disabled={selected === null || selected === ''}
            style={{
              padding: '0.75rem 1.5rem',
              background: '#28a745',
              color: 'white',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer'
            }}
          >
            Check Answer
          </button>
        </>
      ) : (
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: '1.1rem', margin: '1rem 0' }}>
            {isCorrect
              ? <span style={{ color: '#28a745' }}>✅ Correct!</span>
              : <span style={{ color: '#dc3545' }}>
                  ❌ Incorrect. The correct answer was <strong>{current.correct_answer}</strong>.
                </span>
            }
          </p>
          <button
            onClick={handleNext}
            style={{
              padding: '0.75rem 1.5rem',
              background: '#007bff',
              color: 'white',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer'
            }}
          >
            {idx + 1 < questions.length ? 'Next Question' : 'Finish Quiz'}
          </button>
        </div>
      )}
    </div>
  );
}