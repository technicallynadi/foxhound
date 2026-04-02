'use client';

import { useEffect, useState } from 'react';

interface ToastProps {
  type: 'info' | 'success' | 'warning' | 'urgent';
  title: string;
  description?: string;
  action?: { label: string; href?: string; onClick?: () => void };
  autoDismiss?: number; // ms, 0 = manual only
  onDismiss: () => void;
}

const DOT_COLORS: Record<string, string> = {
  info: 'var(--vl)',
  success: 'var(--g)',
  warning: 'var(--warning)',
  urgent: 'var(--error)',
};

const BORDER_COLORS: Record<string, string> = {
  info: 'var(--b)',
  success: 'var(--b)',
  warning: 'rgba(251,191,36,0.15)',
  urgent: 'rgba(248,113,113,0.15)',
};

export default function NotificationToast({ type, title, description, action, autoDismiss = 8000, onDismiss }: ToastProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
    if (autoDismiss > 0 && type !== 'urgent') {
      const t = setTimeout(onDismiss, autoDismiss);
      return () => clearTimeout(t);
    }
  }, [autoDismiss, onDismiss, type]);

  return (
    <div style={{
      position: 'fixed', top: 16, right: 16, zIndex: 9999,
      background: 'var(--sf)', border: `1px solid ${BORDER_COLORS[type]}`,
      borderRadius: 10, padding: '12px 16px', maxWidth: 380, minWidth: 280,
      display: 'flex', gap: 10, alignItems: 'flex-start',
      transform: visible ? 'translateX(0)' : 'translateX(120%)',
      opacity: visible ? 1 : 0,
      transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
      boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
    }}>
      {/* Dot */}
      <span style={{
        width: 8, height: 8, borderRadius: '50%', marginTop: 4, flexShrink: 0,
        background: DOT_COLORS[type],
        animation: type === 'urgent' ? 'pulse 2s infinite' : 'none',
      }} />

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--t)' }}>{title}</div>
        {description && (
          <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>{description}</div>
        )}
        {action && (
          action.href ? (
            <a href={action.href} style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
              textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: 6,
              display: 'inline-block',
            }}>
              {action.label}
            </a>
          ) : (
            <button onClick={action.onClick} style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
              textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: 6,
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            }}>
              {action.label}
            </button>
          )
        )}
      </div>

      {/* Dismiss */}
      <button onClick={onDismiss} style={{
        background: 'none', border: 'none', color: 'var(--t3)',
        cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
      }}>
        &times;
      </button>
    </div>
  );
}
