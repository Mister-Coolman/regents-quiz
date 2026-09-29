import React from 'react';

// Each subject is identified by one flat geometric mark, wherever it appears:
// the subject list, the quiz header, the review cards. Colour in the app is
// reserved for these marks and for right/wrong feedback.
export const SUBJECTS = [
  { name: 'Algebra I',  shape: 'square',   color: 'var(--algebra1)' },
  { name: 'Geometry',   shape: 'triangle', color: 'var(--geometry)' },
  { name: 'Algebra II', shape: 'circle',   color: 'var(--algebra2)' },
];

export function subjectFor(name = '') {
  const n = name.trim().toLowerCase();
  return SUBJECTS.find(s => s.name.toLowerCase() === n) || null;
}

export default function SubjectMark({ subject, size = 14 }) {
  const s = typeof subject === 'string' ? subjectFor(subject) : subject;
  if (!s) return null;

  let shape;
  if (s.shape === 'square') {
    shape = <rect x="1" y="1" width="12" height="12" />;
  } else if (s.shape === 'triangle') {
    shape = <polygon points="7,0.5 13.5,13 0.5,13" />;
  } else {
    shape = <circle cx="7" cy="7" r="6.5" />;
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill={s.color}
      aria-hidden="true"
      style={{ flex: '0 0 auto', display: 'block' }}
    >
      {shape}
    </svg>
  );
}
