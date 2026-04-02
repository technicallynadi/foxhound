'use client';

import { useState } from 'react';
import Link from 'next/link';

export default function LandingNav() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      padding: '16px 48px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      background: 'rgba(8,8,8,0.92)', backdropFilter: 'blur(20px)',
      borderBottom: '1px solid var(--b)',
    }}>
      <Link href="/" style={{
        fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 15,
        letterSpacing: '0.12em', textTransform: 'uppercase' as const,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: 'var(--v)',
          boxShadow: '0 0 10px var(--v), 0 0 20px rgba(139,92,246,0.25)',
        }} />
        Foxhound
      </Link>

      <div className="nav-links-desktop" style={{
        display: 'flex', gap: 36,
        fontFamily: 'var(--font-mono)', fontSize: 11,
        color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase' as const,
      }}>
        <Link href="/#how" style={{ color: 'inherit' }}>How it works</Link>
        <Link href="/#features" style={{ color: 'inherit' }}>Features</Link>
        <Link href="/jobs" style={{ color: 'inherit' }}>Jobs</Link>
      </div>

      <Link href="/login" className="btn-violet nav-cta-desktop">
        Join Early Access →
      </Link>

      <button
        className="nav-hamburger"
        onClick={() => setMenuOpen(!menuOpen)}
        aria-label="Toggle menu"
        style={{
          display: 'none', background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--t)', fontSize: 20, padding: 4,
        }}
      >
        {menuOpen ? '\u2715' : '\u2630'}
      </button>

      {menuOpen && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0,
          background: 'rgba(8,8,8,0.96)', backdropFilter: 'blur(20px)',
          borderBottom: '1px solid var(--b)',
          padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: 16,
        }}>
          <Link href="/#how" onClick={() => setMenuOpen(false)} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>How it works</Link>
          <Link href="/#features" onClick={() => setMenuOpen(false)} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Features</Link>
          <Link href="/jobs" onClick={() => setMenuOpen(false)} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Jobs</Link>
          <Link href="/login" onClick={() => setMenuOpen(false)} className="btn-violet" style={{ textAlign: 'center', marginTop: 8 }}>Join Early Access →</Link>
        </div>
      )}
    </nav>
  );
}
