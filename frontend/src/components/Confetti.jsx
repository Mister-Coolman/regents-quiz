import React, { useEffect, useRef } from 'react';

// Paper rectangles rather than dots, in the exam-booklet palette plus one warm
// accent -- the only place in the app that gets a celebratory colour.
const COLORS = ['#123B6D', '#1E5AA8', '#2E8B4F', '#D8A43B', '#9FC1E8'];

const COUNT = 90;
const DURATION_MS = 2600;
const GRAVITY = 0.12;
const DRAG = 0.995;

function makePiece(width) {
  const angle = -Math.PI / 2 + (Math.random() - 0.5) * 1.1;   // fan upward
  const speed = 5 + Math.random() * 7;
  return {
    x: width * (0.15 + Math.random() * 0.7),
    y: -10 - Math.random() * 40,
    vx: Math.cos(angle) * speed * 0.6,
    vy: Math.sin(angle) * speed + 4,
    w: 5 + Math.random() * 6,
    h: 9 + Math.random() * 8,
    rot: Math.random() * Math.PI,
    vrot: (Math.random() - 0.5) * 0.25,
    color: COLORS[(Math.random() * COLORS.length) | 0],
  };
}

/**
 * One-shot confetti burst drawn over its parent. Renders nothing when the
 * viewer prefers reduced motion.
 */
export default function Confetti() {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const parent = canvas.parentElement;

    const dpr = window.devicePixelRatio || 1;
    let width = parent.clientWidth;
    let height = parent.clientHeight;
    const size = () => {
      width = parent.clientWidth;
      height = parent.clientHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();
    window.addEventListener('resize', size);

    const pieces = Array.from({ length: COUNT }, () => makePiece(width));
    const start = performance.now();
    let raf;

    const frame = (now) => {
      const elapsed = now - start;
      const fade = Math.max(0, 1 - elapsed / DURATION_MS);
      ctx.clearRect(0, 0, width, height);

      for (const p of pieces) {
        p.vy += GRAVITY;
        p.vx *= DRAG;
        p.x += p.vx;
        p.y += p.vy;
        p.rot += p.vrot;

        ctx.save();
        ctx.globalAlpha = fade;
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      }

      if (elapsed < DURATION_MS) {
        raf = requestAnimationFrame(frame);
      } else {
        ctx.clearRect(0, 0, width, height);
      }
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', size);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 5,
      }}
    />
  );
}
