'use client';

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useAgentStream, type AgentMessage, type StreamState, type ToolResult } from '@/lib/useAgentStream';
import { useAuth } from '@/lib/auth-context';

interface AgentContextValue {
  messages: AgentMessage[];
  streamState: StreamState;
  activeToolResult: ToolResult | null;
  sessionId: string | null;
  isOpen: boolean;
  hasNotification: boolean;
  notificationCount: number;
  open: () => void;
  close: () => void;
  toggle: () => void;
  send: (message: string) => void;
  abort: () => void;
  loadHistory: () => void;
  newSession: () => void;
  draft: string;
  setDraft: (v: string) => void;
}

const AgentContext = createContext<AgentContextValue | null>(null);

export function useAgent() {
  const ctx = useContext(AgentContext);
  if (!ctx) throw new Error('useAgent must be used within AgentProvider');
  return ctx;
}

export default function AgentProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id || '';
  const [isOpen, setIsOpen] = useState(false);
  const [hasNotification, setHasNotification] = useState(false);
  const [notificationCount, setNotificationCount] = useState(0);
  const [draft, setDraft] = useState('');
  const lastNotifiedMessageId = useRef<string | null>(null);

  const stream = useAgentStream(userId);

  useEffect(() => {
    const lastMsg = stream.messages[stream.messages.length - 1];
    if (!lastMsg || isOpen) return;
    if (lastMsg.id === lastNotifiedMessageId.current) return;

    const actionable =
      lastMsg.role === 'assistant' &&
      !!lastMsg.toolResult &&
      (
        lastMsg.toolName === 'apply_to_job' ||
        lastMsg.toolName === 'get_dossier' ||
        lastMsg.toolName === 'discover_jobs' ||
        lastMsg.toolName === 'interview_prep'
      );

    if (actionable) {
      lastNotifiedMessageId.current = lastMsg.id;
      const timer = window.setTimeout(() => {
        setHasNotification(true);
        setNotificationCount((prev) => prev + 1);
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [isOpen, stream.messages]);

  const open = () => {
    setIsOpen(true);
    setHasNotification(false);
    setNotificationCount(0);
  };
  const close = () => setIsOpen(false);
  const toggle = () => {
    if (isOpen) close();
    else open();
  };

  return (
    <AgentContext.Provider
      value={{
        ...stream,
        isOpen,
        hasNotification,
        notificationCount,
        draft,
        setDraft,
        open,
        close,
        toggle,
      }}
    >
      {children}
    </AgentContext.Provider>
  );
}
