// Shared helpers for passages and the lines questions cite.

/** "Line 7" or "Lines 12–15" (an en dash, as printed on the exam). */
export function rangeLabel(start, end) {
  return start === end ? `Line ${start}` : `Lines ${start}–${end}`;
}

/** The refs a question makes into one passage, in order. */
export function refsFor(question, stimulusId) {
  return (question?.line_refs || []).filter(r => r.stimulus_id === stimulusId);
}

export function rangeKey(stimulusId, start) {
  return `${stimulusId}:${start}`;
}

/**
 * A passage's lines split into runs: plain lines, and the lines inside each
 * cited range, so a range can be drawn (and focused) as one block.
 */
export function segment(lines, refs) {
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const n = lines[i].n;
    const ref = n == null ? null : refs.find(r => n >= r.start && n <= r.end);
    if (ref) {
      const run = [];
      while (i < lines.length && lines[i].n != null && lines[i].n >= ref.start && lines[i].n <= ref.end) {
        run.push(lines[i++]);
      }
      out.push({ ref, lines: run });
    } else {
      const last = out[out.length - 1];
      if (last && !last.ref) last.lines.push(lines[i]);
      else out.push({ ref: null, lines: [lines[i]] });
      i++;
    }
  }
  return out;
}
