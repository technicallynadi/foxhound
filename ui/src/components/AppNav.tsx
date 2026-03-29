'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

export default function AppNav() {
  const path = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  const links = [
    { href: '/jobs', label: 'Jobs' },
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/applications', label: 'Applications' },
    { href: '/settings', label: 'Settings' },
  ];

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      padding: '16px 48px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      background: 'rgba(8,8,8,0.92)', backdropFilter: 'blur(20px)', borderBottom: '1px solid var(--b)',
    }}>
      <Link href="/" style={{
        fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 15,
        letterSpacing: '0.12em', textTransform: 'uppercase',
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--v)', boxShadow: '0 0 10px var(--v)' }} />
        Foxhound
      </Link>

      <div className="nav-links-desktop" style={{
        display: 'flex', gap: 32,
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
        letterSpacing: '0.08em', textTransform: 'uppercase',
      }}>
        {links.map((l) => (
          <Link key={l.href} href={l.href} style={{ color: path === l.href ? 'var(--t)' : 'inherit' }}>
            {l.label}
          </Link>
        ))}
      </div>

      <Link href="/login" className="btn-violet nav-cta-desktop">Join Beta</Link>

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
          {links.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setMenuOpen(false)} style={{
              fontFamily: 'var(--font-mono)', fontSize: 12,
              color: path === l.href ? 'var(--t)' : 'var(--t2)',
              letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>
              {l.label}
            </Link>
          ))}
          <Link href="/login" onClick={() => setMenuOpen(false)} className="btn-violet" style={{ textAlign: 'center', marginTop: 8 }}>Join Beta</Link>
        </div>
      )}
    </nav>
  );
}
