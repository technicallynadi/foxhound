'use client';

import { useState, useEffect } from 'react';

interface TypewriterTextProps {
  phrases: string[];
  interval?: number;
  typingSpeed?: number;
}

export default function TypewriterText({ phrases, interval = 3000, typingSpeed = 60 }: TypewriterTextProps) {
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [charIndex, setCharIndex] = useState(0);
  const [deleting, setDeleting] = useState(false);

  const currentPhrase = phrases[phraseIndex] || '';

  /* eslint-disable react-hooks/set-state-in-effect -- typing animation drives state via timeouts */
  useEffect(() => {
    if (!deleting && charIndex < currentPhrase.length) {
      const timeout = setTimeout(() => setCharIndex((c) => c + 1), typingSpeed);
      return () => clearTimeout(timeout);
    }

    if (!deleting && charIndex === currentPhrase.length) {
      const timeout = setTimeout(() => setDeleting(true), interval);
      return () => clearTimeout(timeout);
    }

    if (deleting && charIndex > 0) {
      const timeout = setTimeout(() => setCharIndex((c) => c - 1), typingSpeed / 2);
      return () => clearTimeout(timeout);
    }

    if (deleting && charIndex === 0) {
      setDeleting(false);
      setPhraseIndex((i) => (i + 1) % phrases.length);
    }
  }, [charIndex, deleting, currentPhrase, phrases, interval, typingSpeed]); /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <span className="gradient-text" style={{ borderRight: '2px solid var(--v)', paddingRight: 2 }}>
      {currentPhrase.slice(0, charIndex)}
    </span>
  );
}
