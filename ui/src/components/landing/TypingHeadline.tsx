'use client';

import { useEffect, useRef, useState } from 'react';

const WORDS = ['INTERVIEWING.', 'GETTING HIRED.', 'LANDING OFFERS.'];
const TYPE_SPEED = 70;
const DELETE_SPEED = 40;
const HOLD_TIME = 2200;

export default function TypingHeadline() {
  const [displayed, setDisplayed] = useState('');
  const [isDeleting, setIsDeleting] = useState(false);
  const wordIdx = useRef(0);

  /* eslint-disable react-hooks/set-state-in-effect -- typing animation drives state via timeouts */
  useEffect(() => {
    const word = WORDS[wordIdx.current];

    if (!isDeleting && displayed === word) {
      const timer = setTimeout(() => setIsDeleting(true), HOLD_TIME);
      return () => clearTimeout(timer);
    }

    if (isDeleting && displayed === '') {
      wordIdx.current = (wordIdx.current + 1) % WORDS.length;
      setIsDeleting(false);
      return;
    }

    const speed = isDeleting ? DELETE_SPEED : TYPE_SPEED;
    const timer = setTimeout(() => {
      if (isDeleting) {
        setDisplayed(word.substring(0, displayed.length - 1));
      } else {
        setDisplayed(word.substring(0, displayed.length + 1));
      }
    }, speed);

    return () => clearTimeout(timer);
  }, [displayed, isDeleting]); /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <span
      style={{
        color: 'var(--v)',
        fontFamily: 'var(--font-mono)',
        letterSpacing: '-0.02em',
      }}
    >
      {displayed}
      <span
        style={{
          display: 'inline-block',
          width: 3,
          height: '0.7em',
          background: 'var(--v)',
          verticalAlign: 'baseline',
          marginLeft: 2,
          animation: 'cursor-blink 0.6s infinite',
        }}
      />
    </span>
  );
}
