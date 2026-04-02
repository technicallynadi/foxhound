'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

const STEPS = [
  'Submission proof saved',
  'Posting still active',
  'Best contact identified',
  'Outreach draft ready',
  'Follow-up scheduled',
];

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function FormFillDemo() {
  const [status, setStatus] = useState('Building...');
  const [statusColor, setStatusColor] = useState('var(--vl)');
  const [visibleSteps, setVisibleSteps] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  const runFill = useCallback(async () => {
    setStatus('Building...');
    setStatusColor('var(--vl)');

    for (let i = 0; i < STEPS.length; i++) {
      setVisibleSteps(i + 1);
      await sleep(450);
    }
    setStatus('Ready ✓');
    setStatusColor('var(--g)');
  }, []);

  useEffect(() => {
    if (!wrapRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started.current) {
          started.current = true;
          runFill();
        }
      },
      { threshold: 0.2 }
    );
    observer.observe(wrapRef.current);
    return () => observer.disconnect();
  }, [runFill]);

  return (
    <div ref={wrapRef} style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, overflow: 'hidden', height: '100%' }}>
      <div style={{
        padding: '11px 16px', borderBottom: '1px solid var(--b)',
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
        display: 'flex', justifyContent: 'space-between',
      }}>
        <span>Foxhound Brief — Acme AI</span>
        <span style={{ color: statusColor }}>{status}</span>
      </div>

      <div style={{ padding: 20, display: 'grid', gap: 14 }}>
        <div
          style={{
            background: 'rgba(139,92,246,0.04)',
            border: '1px solid rgba(139,92,246,0.08)',
            borderRadius: 8,
            padding: 14,
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--t3)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              marginBottom: 8,
            }}
          >
            Summary
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--t)' }}>
            Stripe — Senior Backend Engineer
          </div>
          <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 4 }}>
            91% match · applied 6:42 AM · brief generated 7:01 AM
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={{ background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8, padding: 14 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
              Submission
            </div>
            <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6 }}>
              Submitted via Greenhouse
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--g)', marginTop: 8 }}>
              Screenshot receipt saved
            </div>
          </div>
          <div style={{ background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8, padding: 14 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
              Posting Status
            </div>
            <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6 }}>
              Active · checked recently
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', marginTop: 8 }}>
              Watchdog enabled
            </div>
          </div>
        </div>

        <div style={{ background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8, padding: 14 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
            Best Contact
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--t)' }}>Sarah Chen</div>
          <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 2 }}>Engineering Manager, Applied AI</div>
          <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6, marginTop: 10 }}>
            Shared Georgia Tech background. Reached the hiring loop three days ago.
          </div>
          <div
            style={{
              marginTop: 10,
              padding: '10px 12px',
              background: 'rgba(139,92,246,0.04)',
              borderLeft: '2px solid var(--v)',
              borderRadius: '0 6px 6px 0',
              fontSize: 12,
              color: 'var(--t2)',
              lineHeight: 1.6,
            }}
          >
            Connection angle: recent post about scaling payments infra matches your distributed systems work.
          </div>
        </div>

        <div style={{ background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8, padding: 14 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
            Next Actions
          </div>
          <div style={{ fontSize: 13, color: 'var(--t3)', lineHeight: 1.6, marginBottom: 10 }}>
            Foxhound already handled the application. What remains is outreach, monitoring, and timing the follow-up.
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {STEPS.map((step, index) => (
              <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: visibleSteps > index ? 1 : 0.35, transition: 'opacity 0.25s' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: visibleSteps > index ? 'var(--g)' : 'var(--b)', display: 'inline-block', flexShrink: 0 }} />
                <span style={{ fontSize: 13, color: visibleSteps > index ? 'var(--t2)' : 'var(--t3)' }}>{step}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
