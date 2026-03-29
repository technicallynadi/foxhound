'use client';

import { useEffect, useRef, useState } from 'react';

interface Props {
  target: number;
  suffix?: string;
  duration?: number;
}

export default function AnimatedCounter({ target, suffix = '', duration = 1200 }: Props) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!ref.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started.current) {
          started.current = true;
          const steps = 35;
          const step = Math.max(1, Math.floor(target / steps));
          let current = 0;
          const timer = setInterval(() => {
            current += step;
            if (current >= target) {
              current = target;
              clearInterval(timer);
            }
            setCount(current);
          }, duration / steps);
        }
      },
      { threshold: 0.4 }
    );

    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [target, duration]);

  return (
    <div
      ref={ref}
      style={{
        fontFamily: 'var(--font-display)',
        fontSize: 32,
        fontWeight: 700,
        letterSpacing: '-0.02em',
        background: 'linear-gradient(135deg, var(--t), var(--vl))',
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundClip: 'text',
      }}
    >
      {count.toLocaleString()}{suffix}
    </div>
  );
}
