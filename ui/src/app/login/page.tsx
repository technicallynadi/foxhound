'use client';

import { useState } from 'react';
import LandingNav from '@/components/landing/LandingNav';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setStatus('loading');
    try {
      const res = await fetch(`${API_BASE}/v1/waitlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      if (res.ok) { setStatus('done'); setEmail(''); }
      else { setStatus('error'); }
    } catch { setStatus('error'); }
  }

  return (
    <main>
      <LandingNav />
      <div style={{
        minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center',
        padding: '120px 20px 80px', position: 'relative', zIndex: 1,
      }}>
        <div style={{
          background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 16,
          padding: '48px 32px', maxWidth: 440, width: '100%', textAlign: 'center',
        }}>
          <div style={{
            width: 12, height: 12, borderRadius: '50%', background: 'var(--v)',
            boxShadow: '0 0 16px var(--v)', margin: '0 auto 24px',
          }} />

          <h1 style={{
            fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700,
            letterSpacing: '-0.02em', marginBottom: 8,
          }}>
            Foxhound is in beta
          </h1>
          <p style={{ fontSize: 14, color: 'var(--t2)', lineHeight: 1.7, marginBottom: 32 }}>
            We&apos;re onboarding users in waves. Drop your email and we&apos;ll let you know when it&apos;s your turn.
          </p>

          {status === 'done' ? (
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--g)',
              padding: '16px 0',
            }}>
              You&apos;re on the list. We&apos;ll be in touch.
            </div>
          ) : (
            <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8 }}>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                maxLength={254}
                className="input"
                style={{ flex: 1, padding: '14px 16px', fontSize: 14 }}
              />
              <button
                type="submit"
                disabled={status === 'loading'}
                className="btn-violet"
                style={{ whiteSpace: 'nowrap' }}
              >
                {status === 'loading' ? '...' : 'Join Beta'}
              </button>
            </form>
          )}

          {status === 'error' && (
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--error)', marginTop: 12 }}>
              Something went wrong. Try again.
            </p>
          )}

        </div>
      </div>
    </main>
  );
}
