import React from 'react';

// Each subject is identified by one flat geometric mark, wherever it appears:
// the subject list, the quiz header, the review cards. Colour in the app is
// reserved for these marks and for right/wrong feedback.
//
// `key` is the subject as the API names it; `name` is what students read.
export const MATH_SUBJECTS = [
  { key: 'Algebra I',  name: 'Algebra I',  shape: 'square',   color: 'var(--algebra1)' },
  { key: 'Geometry',   name: 'Geometry',   shape: 'triangle', color: 'var(--geometry)' },
  { key: 'Algebra II', name: 'Algebra II', shape: 'circle',   color: 'var(--algebra2)' },
];

// ELA: an ink semicircle, half of Algebra II's circle -- a page opened flat.
export const ELA = {
  key: 'ELA', name: 'English Language Arts (ELA)', shape: 'semicircle', color: 'var(--ela)',
};

export const SUBJECTS = [...MATH_SUBJECTS, ELA];

export function subjectFor(name = '') {
  const n = name.trim().toLowerCase();
  return SUBJECTS.find(s => s.key.toLowerCase() === n || s.name.toLowerCase() === n) || null;
}

/** What to call a subject the API names `key`. */
export function subjectLabel(key = '') {
  return subjectFor(key)?.name || key;
}

export default function SubjectMark({ subject, size = 14 }) {
  const s = typeof subject === 'string' ? subjectFor(subject) : subject;
  if (!s) return null;

  let shape;
  if (s.shape === 'square') {
    shape = <rect x="1" y="1" width="12" height="12" />;
  } else if (s.shape === 'triangle') {
    shape = <polygon points="7,0.5 13.5,13 0.5,13" />;
  } else if (s.shape === 'semicircle') {
    shape = <path d="M0.5 10.25 A6.5 6.5 0 0 1 13.5 10.25 Z" />;
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
