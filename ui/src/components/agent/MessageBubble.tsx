'use client';

import type { AgentMessage } from '@/lib/useAgentStream';
import ToolResultCard from './ToolResultCard';

interface Props {
  message: AgentMessage;
}

export default function MessageBubble({ message }: Props) {
  if (message.toolResult && message.toolName) {
    return <ToolResultCard toolName={message.toolName} data={message.toolResult} />;
  }

  const isUser = message.role === 'user';

  return (
    <div style={{
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      padding: '3px 0',
    }}>
      <div style={{
        maxWidth: '88%',
        padding: '11px 15px',
        borderRadius: 10,
        fontSize: 13,
        lineHeight: 1.55,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        ...(isUser
          ? {
              background: 'linear-gradient(135deg, var(--v), var(--vd))',
              color: 'white',
              fontWeight: 500,
            }
          : {
              background: 'var(--el)',
              border: '1px solid var(--b)',
              color: 'var(--t2)',
            }),
      }}>
        {message.content}
      </div>
    </div>
  );
}
