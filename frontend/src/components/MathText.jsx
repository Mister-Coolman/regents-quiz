import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

// The local model emits LaTeX with \( \) / \[ \] delimiters; remark-math
// expects $ $ / $$ $$, so translate before handing off to the renderer.
function normalizeLatexDelimiters(text) {
  if (!text) return '';
  return text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, expr) => `$$${expr}$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, expr) => `$${expr}$`);
}

export default function MathText({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
      {normalizeLatexDelimiters(children)}
    </ReactMarkdown>
  );
}
