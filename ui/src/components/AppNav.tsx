'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { getPendingReportNotifications, dismissReportNotification, getProfile } from '@/lib/api';

export default function AppNav() {
  const path = usePathname();
  const router = useRouter();
  const { user, loading, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [reportToast, setReportToast] = useState<{
    dossier_id: string;
    company: string;
    role: string;
  } | null>(null);
  const toastDismissed = useRef<Set<string>>(new Set());
  const [displayName, setDisplayName] = useState<string | null>(null);

  // Fetch profile display name
  useEffect(() => {
    if (!user) return;
    getProfile()
      .then((p) => {
        const first = (p as Record<string, unknown>).first_name as string || '';
        const last = (p as Record<string, unknown>).last_name as string || '';
        const full = `${first} ${last}`.trim();
        if (full) setDisplayName(full);
      })
      .catch(() => { /* no profile yet */ });
  }, [user]);

  const checkReportNotifications = useCallback(async () => {
    if (!user) return;
    try {
      const data = await getPendingReportNotifications();
      const pending = (data.notifications || []).filter(
        (n) => !toastDismissed.current.has(n.dossier_id),
      );
      if (pending.length > 0) {
        setReportToast(pending[0]);
      }
    } catch {
      // silently ignore — user may not be authenticated yet
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    checkReportNotifications();
    const interval = setInterval(checkReportNotifications, 15000);
    return () => clearInterval(interval);
  }, [user, checkReportNotifications]);

  const handleDismissToast = async () => {
    if (!reportToast) return;
    toastDismissed.current.add(reportToast.dossier_id);
    try {
      await dismissReportNotification(reportToast.dossier_id);
    } catch { /* best-effort */ }
    setReportToast(null);
  };

  const links = [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/applications', label: 'Applications' },
    { href: '/intelligence', label: 'Research' },
    { href: '/settings', label: 'Settings' },
  ];

  const isSignedIn = !loading && !!user;

  /** Derive initials from profile name, then fallback to email */
  const getInitials = (): string => {
    if (displayName) {
      const parts = displayName.split(' ');
      return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase();
    }
    if (!user) return '?';
    return (user.email?.[0] ?? '?').toUpperCase();
  };

  const handleSignOut = async () => {
    await signOut();
    router.push('/');
  };

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

      {isSignedIn && (
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
      )}

      {/* Right side: avatar when signed in, "Join Early Access" when not */}
      {isSignedIn ? (
        <div className="nav-cta-desktop" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Link href="/settings" style={{
            display: 'flex', alignItems: 'center', gap: 8,
            textDecoration: 'none',
          }}>
            <span style={{
              width: 30, height: 30, borderRadius: '50%',
              background: 'var(--vf)', border: '1px solid var(--bv)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
              color: 'var(--vl)', letterSpacing: '0.02em',
              textTransform: 'uppercase', flexShrink: 0,
            }}>
              {getInitials()}
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 11,
              color: 'var(--t2)', letterSpacing: '0.04em',
              maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {displayName || user.email?.split('@')[0] || 'Account'}
            </span>
          </Link>
          <button
            onClick={handleSignOut}
            style={{
              fontFamily: 'var(--font-mono)', fontSize: 10,
              color: 'var(--t3)', letterSpacing: '0.06em', textTransform: 'uppercase',
              background: 'none', border: '1px solid var(--b)', borderRadius: 6,
              padding: '6px 12px', cursor: 'pointer', transition: 'border-color 0.2s',
              minHeight: 30,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--bv)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--b)'; }}
          >
            Sign out
          </button>
        </div>
      ) : (
        <Link href="/jobs" className="btn-violet nav-cta-desktop">Browse Jobs</Link>
      )}

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
          {isSignedIn && links.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setMenuOpen(false)} style={{
              fontFamily: 'var(--font-mono)', fontSize: 12,
              color: path === l.href ? 'var(--t)' : 'var(--t2)',
              letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>
              {l.label}
            </Link>
          ))}
          {isSignedIn ? (
            <>
              <Link href="/settings" onClick={() => setMenuOpen(false)} style={{
                fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t2)',
                letterSpacing: '0.08em', textTransform: 'uppercase',
              }}>
                Profile
              </Link>
              <button
                onClick={() => { setMenuOpen(false); handleSignOut(); }}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t3)',
                  letterSpacing: '0.08em', textTransform: 'uppercase',
                  background: 'none', border: '1px solid var(--b)', borderRadius: 6,
                  padding: '10px 0', cursor: 'pointer', textAlign: 'center', marginTop: 8,
                  minHeight: 44,
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <Link href="/jobs" onClick={() => setMenuOpen(false)} className="btn-violet" style={{ textAlign: 'center', marginTop: 8 }}>Browse Jobs</Link>
          )}
        </div>
      )}
      {/* ─── Report ready toast ─── */}
      {reportToast && (
        <div
          style={{
            position: 'fixed',
            top: 72,
            right: 24,
            zIndex: 99,
            background: 'rgba(12,12,12,0.96)',
            border: '1px solid var(--bv)',
            borderRadius: 12,
            padding: '16px 20px',
            maxWidth: 360,
            boxShadow: '0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(139,92,246,0.1)',
            animation: 'toast-slide-in 0.3s ease-out',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: 'var(--g)', boxShadow: '0 0 8px var(--g)',
              flexShrink: 0, marginTop: 4,
            }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 9,
                color: 'var(--v)', letterSpacing: '0.15em',
                textTransform: 'uppercase', marginBottom: 6,
              }}>
                Research Report Ready
              </div>
              <div style={{
                fontFamily: 'var(--font-display)', fontSize: 14,
                fontWeight: 600, color: 'var(--t)', marginBottom: 2,
              }}>
                {reportToast.company}
              </div>
              {reportToast.role && (
                <div style={{
                  fontFamily: 'var(--font-body)', fontSize: 12,
                  color: 'var(--t3)', marginBottom: 12,
                }}>
                  {reportToast.role}
                </div>
              )}
              <div style={{ display: 'flex', gap: 8 }}>
                <Link
                  href={`/dossier/${reportToast.dossier_id}`}
                  onClick={handleDismissToast}
                  style={{
                    fontFamily: 'var(--font-display)', fontSize: 12,
                    fontWeight: 600, color: 'var(--t)',
                    background: 'var(--vf)', border: '1px solid var(--bv)',
                    borderRadius: 6, padding: '6px 14px',
                    textDecoration: 'none', transition: 'all 0.2s',
                  }}
                >
                  View Report
                </Link>
                <button
                  onClick={handleDismissToast}
                  style={{
                    fontFamily: 'var(--font-mono)', fontSize: 10,
                    color: 'var(--t3)', background: 'none',
                    border: '1px solid var(--b)', borderRadius: 6,
                    padding: '6px 12px', cursor: 'pointer',
                    transition: 'border-color 0.2s',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--bv)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--b)'; }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
          <style>{`
            @keyframes toast-slide-in {
              from { transform: translateY(20px); opacity: 0; }
              to { transform: translateY(0); opacity: 1; }
            }
          `}</style>
        </div>
      )}
    </nav>
  );
}
