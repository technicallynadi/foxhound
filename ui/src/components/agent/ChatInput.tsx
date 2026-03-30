'use client';

import { useRef, type KeyboardEvent } from 'react';

interface Props {
  onSend: (message: string) => void;
  placeholder?: string;
  value: string;
  onChange: (v: string) => void;
}

export default function ChatInput({ onSend, placeholder, value, onChange }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    onChange('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  };

  return (
    <div style={{
      display: 'flex', gap: 8, padding: '10px 14px',
      borderTop: '1px solid var(--b)',
      flexShrink: 0,
    }}>
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        placeholder={placeholder || 'Ask Foxhound...'}
        rows={1}
        className="input"
        style={{
          flex: 1, padding: '9px 12px',
          fontSize: 13, lineHeight: 1.4, resize: 'none',
          minHeight: 38, maxHeight: 120, overflow: 'auto',
        }}
      />
      <button
        onClick={handleSend}
        disabled={!value.trim()}
        aria-label="Send message"
        style={{
          width: 38, height: 38, borderRadius: 6, border: 'none',
          background: value.trim() ? 'var(--v)' : 'rgba(255,255,255,0.04)',
          color: value.trim() ? 'white' : 'var(--t3)',
          cursor: value.trim() ? 'pointer' : 'default',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 700, flexShrink: 0,
          transition: 'background 120ms ease-out, color 120ms ease-out',
        }}
      >
        ↑
      </button>
    </div>
  );
}
