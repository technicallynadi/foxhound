'use client';

import { useEffect, useState } from 'react';

interface ApplyProgressProps {
  company: string;
  title: string;
  matchScore?: number;
  onComplete?: () => void;
  onDismiss: () => void;
}

const STAGES = [
  { key: 'reviewing', label: 'Reviewing your fit', duration: 1500 },
  { key: 'applying', label: 'Filling the application', duration: 2000 },
  { key: 'submitted', label: 'Submitted', duration: 1000 },
  { key: 'researching', label: 'Researching the company', duration: 2000 },
  { key: 'contacts', label: 'Finding who to reach out to', duration: 1500 },
  { key: 'brief', label: 'Your brief is ready', duration: 0 },
];

export default function ApplyProgress({ company, title, matchScore, onComplete, onDismiss }: ApplyProgressProps) {
  const [currentStage, setCurrentStage] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
  }, []);

  useEffect(() => {
    if (currentStage >= STAGES.length - 1) {
      onComplete?.();
      return;
    }
    const timer = setTimeout(() => {
      setCurrentStage((prev) => prev + 1);
    }, STAGES[currentStage].duration);
    return () => clearTimeout(timer);
  }, [currentStage, onComplete]);

  const isComplete = currentStage >= STAGES.length - 1;

  return (
    <div style={{
      position: 'fixed', top: 16, right: 16, zIndex: 9999,
      background: 'var(--sf)', border: '1px solid var(--bv)',
      borderRadius: 10, padding: '16px 20px', width: 340,
      transform: visible ? 'translateX(0)' : 'translateX(120%)',
      opacity: visible ? 1 : 0,
      transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
      boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4,
          }}>
            {isComplete ? 'APPLICATION SENT' : 'APPLYING'}
          </div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>
            {company} — {title}
          </div>
          {matchScore && (
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, marginTop: 2,
              color: matchScore >= 80 ? 'var(--g)' : matchScore >= 70 ? 'var(--vl)' : 'var(--t3)',
            }}>
              {matchScore}% match
            </div>
          )}
        </div>
        <button onClick={onDismiss} style={{
          background: 'none', border: 'none', color: 'var(--t3)',
          cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
        }}>
          &times;
        </button>
      </div>

      {/* Progress stages */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {STAGES.map((stage, i) => {
          const isDone = i < currentStage;
          const isCurrent = i === currentStage;
          const isPending = i > currentStage;

          return (
            <div key={stage.key} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              opacity: isPending ? 0.3 : 1,
              transition: 'opacity 0.3s',
            }}>
              {/* Status dot */}
              <span style={{
                width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                background: isDone ? 'var(--g)' : isCurrent ? 'var(--vl)' : 'var(--t3)',
                animation: isCurrent && !isComplete ? 'pulse 1.5s infinite' : 'none',
              }} />

              {/* Label */}
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 11,
                color: isDone ? 'var(--g)' : isCurrent ? 'var(--t)' : 'var(--t3)',
              }}>
                {stage.label}
                {isDone && ' \u2713'}
              </span>
            </div>
          );
        })}
      </div>

      {/* Close into the tracker when complete */}
      {isComplete && (
        <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid var(--b)' }}>
          <button onClick={onDismiss} style={{
            fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
            textTransform: 'uppercase', letterSpacing: '0.04em',
            background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          }}>
            Open applications &rarr;
          </button>
        </div>
      )}
    </div>
  );
}
