'use client';

import { useRef, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { useAgent } from './AgentProvider';
import { useAuth } from '@/lib/auth-context';
import { isAuthConfigured } from '@/lib/supabase';
import AgentFAB from './AgentFAB';
import AgentPanel from './AgentPanel';

// Pages where the agent widget should NOT appear
const EXCLUDED_PATHS = ['/', '/login'];

export default function AgentWidget() {
  const { user } = useAuth();
  const { isOpen, close } = useAgent();
  const panelRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  const isDevMode = !isAuthConfigured && process.env.NODE_ENV === 'development';
  const shouldShow = !EXCLUDED_PATHS.includes(pathname) && (isDevMode || !!user);

  // Close on click outside — hook always runs (React rules of hooks)
  useEffect(() => {
    if (!isOpen || !shouldShow) return;

    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        close();
      }
    }

    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClick);
    }, 100);

    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClick);
    };
  }, [isOpen, close, shouldShow]);

  if (!shouldShow) return null;

  return (
    <div
      ref={panelRef}
      style={{
        position: 'fixed',
        bottom: 24,
        right: 24,
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: 12,
      }}
    >
      {isOpen && <AgentPanel />}
      {!isOpen && <AgentFAB />}
    </div>
  );
}
