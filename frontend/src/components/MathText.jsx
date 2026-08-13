import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

// remark-math treats every `$` as an inline-math delimiter, which breaks on
// currency: in "Adult tickets ($12.50) and child tickets ($6.25)" it pairs the
// first two dollar signs and renders "12.50) and child tickets (" as math.
//
// For each `$...$` candidate we decide whether the contents are really math.
// Math either carries LaTeX markup or is a symbolic fragment with no prose
// words ("85.75", "9 - 4 = 5", "x = 30"); currency runs into ordinary English.
//
// The scan is done by hand rather than with a global regex replace: when a
// candidate is rejected, only its opening `$` is consumed, so the closing `$`
// stays available to pair with the next opening. A regex replace would swallow
// both and desynchronize the rest of the line, escaping real math after a
// currency amount (e.g. "Cost $50 with $c = 50x$ total").

const LATEX_MARKUP = /[\\^_{}]/;
// Three or more consecutive letters reads as an English word. Math variables
// and their products stay under that ("y = mx + b", "c = 50x"), so this keeps
// algebra as math while treating "($12.50) and child tickets (" as prose.
const PROSE_WORD = /[A-Za-z]{3,}/;

function looksLikeMath(inner) {
  if (!inner.trim()) return false;
  if (LATEX_MARKUP.test(inner)) return true;
  if (inner.length > 60) return false;
  // A relational operator means this is a formula, even when the variable
  // names read like words ("I = Prt", "time = distance/speed"). Prose that
  // merely spans two currency amounts never contains one.
  if (/[=<>≤≥≠]/.test(inner)) return true;
  return !PROSE_WORD.test(inner);
}

// Index of the next `$` at or after `from` that isn't backslash-escaped. The
// model sometimes writes currency inside math as `$\$6$`, and that inner `\$`
// must not be mistaken for a delimiter.
function nextDelimiter(text, from) {
  for (let j = from; j < text.length; j++) {
    if (text[j] === '$' && text[j - 1] !== '\\') return j;
  }
  return -1;
}

function protectMath(text) {
  let out = '';
  let i = 0;

  while (i < text.length) {
    if (text[i] !== '$' || text[i - 1] === '\\') {
      out += text[i++];
      continue;
    }

    // Block math: `$$...$$` is unambiguous, never currency.
    if (text[i + 1] === '$') {
      const end = text.indexOf('$$', i + 2);
      if (end !== -1) {
        out += text.slice(i, end + 2);
        i = end + 2;
        continue;
      }
    }

    // Inline candidate: look for a closing `$` on the same line.
    const lineEnd = text.indexOf('\n', i + 1);
    const searchEnd = lineEnd === -1 ? text.length : lineEnd;
    const close = nextDelimiter(text, i + 1);

    if (close !== -1 && close < searchEnd && looksLikeMath(text.slice(i + 1, close))) {
      out += text.slice(i, close + 1);
      i = close + 1;
    } else {
      // Literal dollar sign (currency, or an unpaired stray).
      out += '\\$';
      i += 1;
    }
  }

  return out;
}

// Models sometimes emit \( \) / \[ \] instead of $ $ / $$ $$.
function normalizeLatexDelimiters(text) {
  if (!text) return '';
  return text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, expr) => `$$${expr}$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, expr) => `$${expr}$`);
}

export function prepareMath(text) {
  return protectMath(normalizeLatexDelimiters(text || ''));
}

export default function MathText({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
      {prepareMath(children)}
    </ReactMarkdown>
  );
}
