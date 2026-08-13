// Explanations are generated in a fixed four-section shape, enforced by a
// validator in scripts/fireworks_explanations.py:
//
//   **What's being asked**  one sentence
//   **Approach**            the concept or method
//   **Work**                numbered steps
//   **Answer**              the result
//
// That guarantee is what makes them safe to take apart here and reveal a
// piece at a time.

const HEADINGS = [
  ['asked', "What's being asked"],
  ['approach', 'Approach'],
  ['work', 'Work'],
  ['answer', 'Answer'],
];

function sectionBody(text, label) {
  // Escape regex metacharacters first, then widen the apostrophe to accept
  // either variant the model emits in "What's being asked". Doing it the other
  // way round escapes the brackets of the character class itself.
  const escaped = label
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/'/g, "['’]");
  const re = new RegExp(`\\*\\*${escaped}\\*\\*([\\s\\S]*?)(?=\\n\\s*\\*\\*|$)`, 'i');
  const m = text.match(re);
  return m ? m[1].trim() : '';
}

// A step starts at "1." / "2." at the beginning of a line. Steps can run over
// several lines and contain $$ blocks, so split on those boundaries rather
// than treating every line as a step.
function splitSteps(work) {
  if (!work) return [];
  const parts = work.split(/\n(?=\s*\d+\.\s)/);
  return parts
    .map(s => s.trim().replace(/^\d+\.\s*/, '').trim())
    .filter(Boolean);
}

export function parseExplanation(text) {
  if (!text || typeof text !== 'string') return null;
  const out = {};
  for (const [key, label] of HEADINGS) out[key] = sectionBody(text, label);
  if (!out.asked && !out.approach && !out.work) return null;
  return { ...out, steps: splitSteps(out.work) };
}

// How many work steps a student may unlock before answering. Enough to get
// unstuck, not enough to hand over the solution.
export const MAX_HINT_STEPS = 2;

/** Ordered hints: framing first, then method, then the opening steps. */
export function buildHints(text) {
  const parsed = parseExplanation(text);
  if (!parsed) return [];
  const hints = [];
  if (parsed.asked) hints.push({ label: "What's being asked", body: parsed.asked });
  if (parsed.approach) hints.push({ label: 'Approach', body: parsed.approach });
  parsed.steps.slice(0, MAX_HINT_STEPS).forEach((body, i) => {
    hints.push({ label: `Step ${i + 1}`, body });
  });
  return hints;
}
