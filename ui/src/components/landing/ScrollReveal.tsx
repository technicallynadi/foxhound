'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import clsx from 'clsx';

interface Props {
  children: ReactNode;
  delay?: number;
  className?: string;
}

export default function ScrollReveal({ children, delay = 0, className }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  const delayClass = delay > 0 ? `reveal-d${Math.min(delay, 4)}` : '';

  return (
    <div ref={ref} className={clsx('reveal', delayClass, className)}>
      {children}
    </div>
  );
}
