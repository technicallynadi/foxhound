'use client';

import { useEffect } from 'react';
import { useAgent } from './AgentProvider';
import MessageList from './MessageList';
import ChatInput from './ChatInput';

export default function AgentPanel() {
  const { messages, streamState, send, close, loadHistory, newSession, draft, setDraft } = useAgent();

  useEffect(() => { if (messages.length === 0) loadHistory(); }, [loadHistory, messages.length]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [close]);

  return (
    <div
      role="dialog"
      aria-label="Foxhound agent"
      aria-modal="false"
      className="agent-panel"
      style={{
        width: 400, height: 560, maxHeight: '80vh',
        display: 'flex', flexDirection: 'column',
        background: 'rgba(14, 14, 14, 0.9)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        border: '1px solid var(--bv)',
        borderRadius: 16,
        boxShadow: '0 24px 64px rgba(0,0,0,0.7), 0 0 48px rgba(139,92,246,0.06)',
        overflow: 'hidden',
        animation: 'panel-open 250ms cubic-bezier(0.34, 1.56, 0.64, 1)',
        transformOrigin: 'bottom right',
      }}
    >
      {/* Header — matches landing page ChatDemo exactly */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '11px 16px', borderBottom: '1px solid var(--b)', flexShrink: 0,
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
      }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: 'var(--v)', boxShadow: '0 0 6px var(--v)',
          animation: 'status-pulse 2s infinite',
        }} />
        FOXHOUND AGENT
        <span style={{ marginLeft: 'auto', color: streamState !== 'idle' ? 'var(--vl)' : 'var(--g)' }}>
          {streamState !== 'idle' ? 'WORKING...' : 'ACTIVE'}
        </span>
      </div>

      <MessageList messages={messages} streamState={streamState} onSend={send} />

      <ChatInput
        onSend={send}
        placeholder="Ask Foxhound anything..."
        value={draft}
        onChange={setDraft}
      />

      <style jsx>{`
        @keyframes panel-open {
          from { opacity: 0; transform: scale(0.9) translateY(8px); }
          to   { opacity: 1; transform: scale(1) translateY(0); }
        }
        @media (max-width: 768px) {
          .agent-panel {
            width: 100vw !important;
            height: 70vh !important;
            max-height: 70vh !important;
            border-radius: 16px 16px 0 0 !important;
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            right: 0 !important;
            top: auto !important;
          }
        }
      `}</style>
    </div>
  );
}
