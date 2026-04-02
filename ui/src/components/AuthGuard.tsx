'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { isAuthConfigured } from '@/lib/supabase';

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    // Always redirect unauthenticated users — whether auth is configured or not
    if (!loading && !user) {
      router.push('/login');
    }
  }, [user, loading, router]);

  // Auth not configured
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
    // Production without auth configured — redirect to landing, never show app
    return (
      <div style={{ minHeight: '100vh', background: 'var(--bg)' }} />
    );
  }

  // Auth configured but still loading session
  if (loading) {
    return (
      <div style={{ minHeight: '100vh', background: 'var(--bg)' }} />
    );
  }

  // Not authenticated — redirect is happening via useEffect, render nothing
  if (!user) {
    return (
      <div style={{ minHeight: '100vh', background: 'var(--bg)' }} />
    );
  }

  return <>{children}</>;
}
