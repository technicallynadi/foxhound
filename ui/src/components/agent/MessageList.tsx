'use client';

import { useEffect, useRef } from 'react';
import type { AgentMessage, StreamState } from '@/lib/useAgentStream';
import MessageBubble from './MessageBubble';

interface Props {
  messages: AgentMessage[];
  streamState: StreamState;
}

export default function MessageList({ messages, streamState }: Props) {
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
          <div style={{ fontSize: 12, color: 'var(--t3)', maxWidth: 220, lineHeight: 1.5 }}>
            Your personal career agent. Try &quot;find me ML jobs&quot; or &quot;apply to this role&quot;.
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {/* Typing indicator */}
      {(streamState === 'tool_executing' || streamState === 'streaming') && (
        <div style={{ display: 'flex', gap: 4, padding: '8px 15px', alignSelf: 'flex-start' }}>
          {[0, 1, 2].map((i) => (
            <span key={i} style={{
              width: 5, height: 5, borderRadius: '50%', background: 'var(--t3)',
              animation: `typing-bounce 1.4s infinite ${i * 0.2}s`,
            }} />
          ))}
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
