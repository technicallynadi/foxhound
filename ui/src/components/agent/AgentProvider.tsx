'use client';

import { createContext, useContext, useState, type ReactNode } from 'react';
import { useAgentStream, type AgentMessage, type StreamState, type ToolResult } from '@/lib/useAgentStream';
import { useAuth } from '@/lib/auth-context';

interface AgentContextValue {
  messages: AgentMessage[];
  streamState: StreamState;
  activeToolResult: ToolResult | null;
  sessionId: string | null;
  isOpen: boolean;
  hasNotification: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
  send: (message: string) => void;
  abort: () => void;
  loadHistory: () => void;
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

  const stream = useAgentStream(userId);

  const open = () => {
    setIsOpen(true);
    setHasNotification(false);
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
        open,
        close,
        toggle,
      }}
    >
      {children}
    </AgentContext.Provider>
  );
}
