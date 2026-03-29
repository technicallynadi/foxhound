'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { isAuthConfigured } from '@/lib/supabase';

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isAuthConfigured) return;
    if (!loading && !user) {
      router.push('/login');
    }
  }, [user, loading, router]);

  // Auth not configured — show setup notice in dev, block in prod
  if (!isAuthConfigured) {
    if (process.env.NODE_ENV === 'development') {
      // Dev mode — allow through with a warning banner
      return (
        <>
          <div style={{
            background: '#f59e0b', color: '#000', fontSize: 12, fontWeight: 600,
            textAlign: 'center', padding: '4px 8px',
          }}>
            DEV MODE — Auth not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.
          </div>
          {children}
        </>
      );
    }
    // Production — do not bypass
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100vh', color: 'var(--color-error)', fontSize: 14, textAlign: 'center', padding: 24,
      }}>
        Authentication is not configured. Please contact support.
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100vh', color: 'var(--text-muted)', fontSize: 14,
      }}>
        Loading...
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return <>{children}</>;
}
