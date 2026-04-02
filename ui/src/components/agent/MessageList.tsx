'use client';

import { useEffect, useRef } from 'react';
import type { AgentMessage, StreamState } from '@/lib/useAgentStream';
import MessageBubble from './MessageBubble';

interface Props {
  messages: AgentMessage[];
  streamState: StreamState;
  onSend?: (message: string) => void;
}

export default function MessageList({ messages, streamState, onSend }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamState]);

  return (
    <div role="log" aria-label="Agent messages" style={{
      flex: 1, overflowY: 'auto', padding: 16,
      display: 'flex', flexDirection: 'column', gap: 6,
    }}>
      {messages.length === 0 && (
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 12,
          textAlign: 'center', padding: 32,
        }}>
          <div style={{
            width: 32, height: 32, borderRadius: '50%',
            background: 'linear-gradient(135deg, var(--v), var(--vd))',
            opacity: 0.6,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="4" fill="white" />
              <circle cx="12" cy="12" r="8" stroke="white" strokeWidth="1.5" opacity="0.5" />
            </svg>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600, color: 'var(--t2)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            foxhound agent
          </div>
          <div style={{ fontSize: 13, color: 'var(--t2)', maxWidth: 240, lineHeight: 1.6 }}>
            Hey! I&apos;m your career agent. What can I help you with?
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4, width: '100%', maxWidth: 220 }}>
            {[
              'Show my top matches',
              'Show my tracked applications',
              'Apply to my best match',
              'Open people research for my latest application',
            ].map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => onSend?.(suggestion)}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.03em',
                  padding: '6px 12px', borderRadius: 6, cursor: 'pointer',
                  background: 'var(--bg)', border: '1px solid var(--b)',
                  color: 'var(--t3)', transition: 'all 0.15s', textAlign: 'left',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--bv)'; e.currentTarget.style.color = 'var(--vl)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--b)'; e.currentTarget.style.color = 'var(--t3)'; }}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} onSend={onSend} />
      ))}

      {/* Status indicator */}
      {streamState === 'streaming' && (
        <div style={{ display: 'flex', gap: 4, padding: '8px 15px', alignSelf: 'flex-start' }}>
          {[0, 1, 2].map((i) => (
            <span key={i} style={{
              width: 5, height: 5, borderRadius: '50%', background: 'var(--t3)',
              animation: `typing-bounce 1.4s infinite ${i * 0.2}s`,
            }} />
          ))}
        </div>
      )}
      {streamState === 'tool_executing' && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 15px',
          alignSelf: 'flex-start',
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: 'var(--v)',
            boxShadow: '0 0 6px var(--v)', animation: 'status-pulse 2s infinite',
          }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            Working on it...
          </span>
        </div>
      )}

      <div ref={bottomRef} />

      <style jsx>{`
        @keyframes typing-bounce {
          0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
          30% { opacity: 1; transform: translateY(-3px); }
        }
      `}</style>
    </div>
  );
}
