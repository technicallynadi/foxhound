'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { usePathname } from 'next/navigation';
import { useAgent } from './AgentProvider';
import { useAuth } from '@/lib/auth-context';
import { isAuthConfigured } from '@/lib/supabase';
import AgentFAB from './AgentFAB';
import AgentPanel from './AgentPanel';
import ApplyProgress from '@/components/notifications/ApplyProgress';

// Pages where the agent widget should NOT appear
const EXCLUDED_PATHS = ['/', '/login', '/onboard'];

interface ApplyNotification {
  company: string;
  title: string;
  matchScore?: number;
  applicationId?: string;
}

export default function AgentWidget() {
  const { user } = useAuth();
  const { isOpen, close, messages } = useAgent();
  const panelRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const [applyNotification, setApplyNotification] = useState<ApplyNotification | null>(null);

  const isDevMode = !isAuthConfigured && process.env.NODE_ENV === 'development';
  const shouldShow = !EXCLUDED_PATHS.includes(pathname) && (isDevMode || !!user);

  // Detect when agent submits an application — show the ApplyProgress notification
  useEffect(() => {
    if (!messages.length) return;
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role !== 'assistant' || !lastMsg.toolName || !lastMsg.toolResult) return;

    if (lastMsg.toolName === 'apply_to_job') {
      const r = lastMsg.toolResult as Record<string, unknown>;
      if (r.status === 'submitted' || r.status === 'scanning' || r.status === 'in_progress') {
        const timer = window.setTimeout(() => {
          setApplyNotification({
            company: String(r.company || ''),
            title: String(r.job_title || ''),
            matchScore: typeof r.match_score === 'number' ? r.match_score : undefined,
            applicationId: String(r.application_id || ''),
          });
        }, 0);
        return () => window.clearTimeout(timer);
      }
    }
  }, [messages]);

  // Close on click outside
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

  const dismissApply = useCallback(() => setApplyNotification(null), []);

  if (!shouldShow) return null;

  return (
    <>
      {/* Apply progress notification — top right, independent of panel */}
      {applyNotification && (
        <ApplyProgress
          company={applyNotification.company}
          title={applyNotification.title}
          matchScore={applyNotification.matchScore}
          onComplete={() => {
            // Could navigate to brief here
          }}
          onDismiss={dismissApply}
        />
      )}

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
    </>
  );
}
