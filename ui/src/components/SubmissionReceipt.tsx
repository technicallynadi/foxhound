'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

/* ─── Types ─── */

export interface SubmissionReceiptProps {
  company: string;
  role: string;
  submittedAt: string; // ISO date
  fieldsFilled: string[]; // list of field labels
  applicationId: string;
  atsType?: string; // "greenhouse" | "lever" | "ashby"
  submissionMethod?: string; // "api" | "browser"
}

/* ─── Constants ─── */

const ATS_DISPLAY: Record<string, string> = {
  greenhouse: 'Greenhouse',
  lever: 'Lever',
  ashby: 'Ashby',
  workday: 'Workday',
  icims: 'iCIMS',
  taleo: 'Taleo',
  smartrecruiters: 'SmartRecruiters',
};

/* ─── Helpers ─── */

function formatReceiptDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }) + ' at ' + d.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  } catch {
    return iso;
  }
}

function truncateId(id: string): string {
  if (id.length <= 12) return id;
  return id.slice(0, 6).toUpperCase() + '-' + id.slice(-4).toUpperCase();
}

/* ─── Receipt Modal ─── */

export function SubmissionReceipt({
  company,
  role,
  submittedAt,
  fieldsFilled,
  applicationId,
  atsType,
  onClose,
}: SubmissionReceiptProps & { onClose: () => void }) {
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Trap focus inside modal
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    contentRef.current?.focus();
    return () => { prev?.focus(); };
  }, []);

  const atsDisplayName = atsType ? (ATS_DISPLAY[atsType.toLowerCase()] || atsType) : null;

  return (
    <div
      onClick={onClose}
      role="dialog"
      aria-label={`Submission receipt for ${company}`}
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 300,
        background: 'rgba(0, 0, 0, 0.82)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        animation: 'receipt-fade-in 0.2s ease-out',
      }}
    >
      <div
        ref={contentRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'relative',
          maxWidth: 460,
          width: '100%',
          maxHeight: '90vh',
          overflowY: 'auto',
          outline: 'none',
        }}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          aria-label="Close receipt"
          style={{
            position: 'absolute',
            top: -40,
            right: 0,
            width: 32,
            height: 32,
            borderRadius: 8,
            border: 'none',
            background: 'rgba(255,255,255,0.08)',
            color: 'var(--t2)',
            cursor: 'pointer',
            fontSize: 16,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'background 0.2s',
            zIndex: 2,
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.14)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; }}
        >
          &times;
        </button>

        {/* Receipt card */}
        <div style={{
          background: 'var(--sf)',
          border: '1px solid var(--b)',
          borderRadius: 14,
          overflow: 'hidden',
        }}>

          {/* ── Header ── */}
          <div style={{
            padding: '28px 28px 20px',
            borderBottom: '1px solid var(--b)',
            position: 'relative',
            overflow: 'hidden',
          }}>
            {/* Subtle gradient behind header */}
            <div style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              height: 120,
              background: 'linear-gradient(135deg, rgba(139,92,246,0.06) 0%, rgba(52,211,153,0.04) 100%)',
              pointerEvents: 'none',
            }} aria-hidden="true" />

            {/* Logo row */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              marginBottom: 16,
              position: 'relative',
            }}>
              {/* Foxhound icon */}
              <div style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                background: 'var(--v)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" fill="white" />
                </svg>
              </div>
              <span style={{
                fontFamily: 'var(--font-display)',
                fontSize: 15,
                fontWeight: 700,
                letterSpacing: '-0.02em',
                color: 'var(--t)',
              }}>
                Foxhound
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                color: 'var(--t3)',
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                marginLeft: 'auto',
              }}>
                Application Receipt
              </span>
            </div>

            {/* Status */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              position: 'relative',
            }}>
              {/* Checkmark circle */}
              <div style={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                background: 'rgba(52,211,153,0.1)',
                border: '1.5px solid rgba(52,211,153,0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}>
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                  <path
                    d="M4 9.5L7.5 13L14 5"
                    stroke="var(--g)"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
              <div>
                <div style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 18,
                  fontWeight: 700,
                  letterSpacing: '-0.02em',
                  color: 'var(--g)',
                  lineHeight: 1.2,
                }}>
                  Submitted Successfully
                </div>
                <div style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--t3)',
                  letterSpacing: '0.04em',
                  marginTop: 2,
                }}>
                  Your application has been delivered
                </div>
              </div>
            </div>
          </div>

          {/* ── Details Grid ── */}
          <div style={{ padding: '20px 28px' }}>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--vl)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              marginBottom: 14,
            }}>
              Submission Details
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr',
              gap: 0,
            }}>
              <DetailRow label="Company" value={company} />
              <DetailRow label="Role" value={role} />
              <DetailRow label="Submitted" value={formatReceiptDate(submittedAt)} />
              <DetailRow label="Method" value="Direct submission" />
              {atsDisplayName && (
                <DetailRow label="Confirmation" value={`Received by ${atsDisplayName}`} />
              )}
            </div>
          </div>

          {/* ── Fields Submitted ── */}
          {fieldsFilled.length > 0 && (
            <div style={{
              padding: '0 28px 20px',
            }}>
              <div style={{
                borderTop: '1px solid var(--b)',
                paddingTop: 20,
              }}>
                <div style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  color: 'var(--vl)',
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  marginBottom: 12,
                }}>
                  Fields Submitted ({fieldsFilled.length})
                </div>

                <FieldsList fields={fieldsFilled} />
              </div>
            </div>
          )}

          {/* ── Footer ── */}
          <div style={{
            padding: '16px 28px',
            borderTop: '1px solid var(--b)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'rgba(0,0,0,0.15)',
          }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--t3)',
              letterSpacing: '0.06em',
            }}>
              Powered by Foxhound
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--t3)',
              letterSpacing: '0.06em',
            }}>
              ID {truncateId(applicationId)}
            </span>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes receipt-fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </div>
  );
}


/* ─── Detail Row ─── */

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline',
      padding: '8px 0',
      borderBottom: '1px solid rgba(255,255,255,0.03)',
      gap: 16,
    }}>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--t3)',
        letterSpacing: '0.03em',
        flexShrink: 0,
        textTransform: 'uppercase',
      }}>
        {label}
      </span>
      <span style={{
        fontFamily: 'var(--font-body)',
        fontSize: 13,
        color: 'var(--t)',
        textAlign: 'right',
        lineHeight: 1.4,
        minWidth: 0,
        wordBreak: 'break-word',
      }}>
        {value}
      </span>
    </div>
  );
}


/* ─── Fields List (collapsible beyond 6) ─── */

function FieldsList({ fields }: { fields: string[] }) {
  const VISIBLE_THRESHOLD = 6;
  const [expanded, setExpanded] = useState(false);

  const shouldCollapse = fields.length > VISIBLE_THRESHOLD;
  const visible = shouldCollapse && !expanded ? fields.slice(0, VISIBLE_THRESHOLD) : fields;
  const hiddenCount = fields.length - VISIBLE_THRESHOLD;

  return (
    <div>
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6,
      }}>
        {visible.map((field, i) => (
          <span
            key={i}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--t2)',
              letterSpacing: '0.02em',
              padding: '4px 10px',
              borderRadius: 4,
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.04)',
              lineHeight: 1.4,
            }}
          >
            {field}
          </span>
        ))}
      </div>

      {shouldCollapse && (
        <button
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-label={expanded ? 'Show fewer fields' : `Show ${hiddenCount} more fields`}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--vl)',
            letterSpacing: '0.04em',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: '8px 0 0',
            transition: 'color 0.2s',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--v)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--vl)'; }}
        >
          {expanded ? 'Show less' : `+${hiddenCount} more`}
        </button>
      )}
    </div>
  );
}


/* ─── Receipt Thumbnail ─── */

export function ReceiptThumbnail({
  company,
  onClick,
}: {
  company: string;
  onClick: () => void;
}) {
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick();
    }
  }, [onClick]);

  return (
    <button
      onClick={onClick}
      onKeyDown={handleKeyDown}
      aria-label={`View submission receipt for ${company}`}
      title="View submission receipt"
      style={{
        width: 48,
        height: 36,
        borderRadius: 5,
        overflow: 'hidden',
        border: '1px solid var(--b)',
        padding: 0,
        cursor: 'pointer',
        background: 'var(--bg)',
        flexShrink: 0,
        position: 'relative',
        transition: 'border-color 0.2s, box-shadow 0.2s',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'rgba(52,211,153,0.3)';
        e.currentTarget.style.boxShadow = '0 0 10px rgba(52,211,153,0.1)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--b)';
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      {/* Background tint */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          background: 'linear-gradient(135deg, rgba(139,92,246,0.08), rgba(52,211,153,0.06))',
        }}
      />

      {/* Checkmark icon */}
      <div
        aria-hidden="true"
        style={{
          position: 'relative',
          width: 18,
          height: 18,
          borderRadius: '50%',
          background: 'rgba(52,211,153,0.12)',
          border: '1px solid rgba(52,211,153,0.25)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path
            d="M2 5.2L4.2 7.4L8 3"
            stroke="var(--g)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>

      {/* Expand indicator — matches ScreenshotThumbnail */}
      <span
        aria-hidden="true"
        style={{
          position: 'absolute',
          bottom: 2,
          right: 2,
          width: 12,
          height: 12,
          borderRadius: 2,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <svg width="7" height="7" viewBox="0 0 7 7" fill="none">
          <path d="M0 0H3V1H1V3H0V0Z" fill="rgba(255,255,255,0.6)" />
          <path d="M7 7H4V6H6V4H7V7Z" fill="rgba(255,255,255,0.6)" />
        </svg>
      </span>
    </button>
  );
}


/* ─── Default Export ─── */

export default SubmissionReceipt;
