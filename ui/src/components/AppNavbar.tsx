'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { isAuthConfigured } from '@/lib/supabase';

const NAV_LINKS = [
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/jobs', label: 'Jobs' },
  { href: '/applications', label: 'Applications' },
  { href: '/settings', label: 'Settings' },
];

export default function AppNavbar() {
  const pathname = usePathname();
  const { user, signOut } = useAuth();

  return (
    <nav className="glass-nav">
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: 56, padding: '0 24px', maxWidth: 1200, margin: '0 auto', width: '100%',
      }}>
        <Link href="/dashboard">
          <div style={{
            fontWeight: 700, fontSize: 15, letterSpacing: '-0.03em',
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <div style={{
              width: 12, height: 12, borderRadius: '50%',
              background: 'linear-gradient(135deg, #4b9eff, #9333ea)',
            }} />
            FOXHOUND
          </div>
        </Link>

        {user && (
          <div style={{ display: 'flex', gap: 4, fontSize: 13 }}>
            {NAV_LINKS.map((link) => {
              const isActive = pathname === link.href || pathname.startsWith(link.href + '/');
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 8,
                    color: isActive ? '#fff' : 'var(--text-muted)',
                    fontWeight: isActive ? 500 : 400,
                    background: isActive ? 'rgba(255,255,255,0.06)' : 'transparent',
                    transition: 'background 150ms ease-out, color 150ms ease-out',
                  }}
                >
                  {link.label}
                </Link>
              );
            })}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 100, justifyContent: 'flex-end' }}>
          {isAuthConfigured && user ? (
            <>
              <span style={{
                fontSize: 12, color: 'var(--text-secondary)',
                maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {user.email}
              </span>
              <button onClick={signOut} className="btn-ghost" style={{ height: 28, padding: '0 10px', fontSize: 11 }}>
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" style={{ fontSize: 13, color: 'var(--text-muted)' }}>Sign in</Link>
          )}
        </div>
      </div>
    </nav>
  );
}
