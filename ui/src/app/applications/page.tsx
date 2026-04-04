'use client';

import { useEffect, useState, useCallback, type FormEvent } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import PageSkeleton from '@/components/PageSkeleton';
import ScrollReveal from '@/components/landing/ScrollReveal';
import { archiveApplication, listApplications, trackManualApplication, triggerWatchdogCheck } from '@/lib/api';

/* ─── Types ─── */

interface AppItem {
  id: string;
  status: string;
  trigger: string;
  brief_ready: boolean;
  brief_status?: string | null;
  job: { id: string; title: string; company: string; ats_type: string };
  tinyfish_status: string | null;
  screenshot_url: string | null;
  submitted_at: string | null;
  created_at: string | null;
  posting_status?: string | null;
  last_watchdog_check_at?: string | null;
  posting_diff_summary?: string | null;
}

type ViewMode = 'list' | 'kanban';
type PostingStatus = 'active' | 'edited' | 'removed' | 'reposted' | 'unknown';

/* ─── Config ─── */

const STATUS_CONFIG: Record<string, { color: string; label: string; pulse?: boolean }> = {
  submitted: { color: 'var(--g)', label: 'Applied' },
  scanning: { color: 'var(--vl)', label: 'In Progress', pulse: true },
  in_progress: { color: 'var(--vl)', label: 'In Progress', pulse: true },
  waiting_user_input: { color: 'var(--vl)', label: 'Questions Pending' },
  failed: { color: 'var(--error)', label: 'Failed' },
  needs_manual: { color: 'var(--warning)', label: 'Needs Attention' },
  canceled: { color: 'var(--t3)', label: 'Canceled' },
};

const POSTING_STATUS_CONFIG: Record<PostingStatus, { color: string; label: string }> = {
  active:   { color: '#34D399', label: 'Active' },
  edited:   { color: '#FBBF24', label: 'Edited' },
  removed:  { color: '#F87171', label: 'Removed' },
  reposted: { color: '#A78BFA', label: 'Reposted' },
  unknown:  { color: 'rgba(240,240,240,0.42)', label: 'Not checked' },
};

const KANBAN_COLUMNS: { key: PostingStatus; title: string }[] = [
  { key: 'unknown', title: 'Applied' },
  { key: 'active', title: 'Active' },
  { key: 'edited', title: 'Edited' },
  { key: 'removed', title: 'Removed' },
];

/* ─── Helpers ─── */

function daysAgo(dateStr: string | null): string {
  if (!dateStr) return '';
  const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === 1) return '1 day ago';
  return `${diff}d ago`;
}

function daysSince(dateStr: string | null): number | null {
  if (!dateStr) return null;
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000);
}

function runActorLabel(trigger: string): string {
  if (trigger === 'autopilot' || trigger === 'agent' || trigger === 'resume_fill') {
    return 'Foxhound';
  }
  if (trigger === 'manual_import' || trigger === 'manual_track') {
    return 'You';
  }
  return 'Foxhound';
}

function researchHref(tab: 'people' | 'brief' | 'interview' | 'status', app: AppItem): string {
  const params = new URLSearchParams({
    tab,
    company: app.job.company,
    role: app.job.title,
    applicationId: app.id,
  });
  return `/intelligence?${params.toString()}`;
}

function nextStepForApplication(app: AppItem): { label: string; detail: string; href?: string } {
  const age = daysSince(app.submitted_at || app.created_at);

  if (app.status === 'canceled') {
    return {
      label: 'Archived',
      detail: 'Foxhound has stopped prioritizing this role. You can still reopen the brief or research context if you need to revisit it.',
      href: app.brief_ready ? `/brief/${app.id}` : researchHref('status', app),
    };
  }

  if (app.status === 'waiting_user_input') {
    return {
      label: 'Answer pending questions',
      detail: 'Foxhound is waiting for your answers before it can finish this application.',
    };
  }

  if (app.status === 'needs_manual') {
    return {
      label: 'Review manual handoff',
      detail: 'Foxhound hit an edge case and needs help finishing the workflow.',
    };
  }

  if (app.posting_status === 'removed') {
    return {
      label: 'Archive or stop follow-up',
      detail: 'This posting looks closed. Foxhound should stop prioritizing follow-up here unless you already have traction.',
      href: researchHref('status', app),
    };
  }

  if (app.posting_status === 'edited') {
    return {
      label: 'Review posting changes',
      detail: 'The role changed after you applied. Double-check the brief and adjust follow-up if needed.',
      href: app.brief_ready ? `/brief/${app.id}` : researchHref('brief', app),
    };
  }

  if (typeof age === 'number' && age >= 7) {
    return {
      label: 'Follow up now',
      detail: 'Foxhound should draft the next follow-up and refresh people research before you reach out.',
      href: researchHref('people', app),
    };
  }

  if (typeof age === 'number' && age >= 3) {
    return {
      label: 'Monitor for movement',
      detail: 'Foxhound is in the first follow-up window. Keep the brief handy and watch for status changes.',
      href: app.brief_ready ? `/brief/${app.id}` : researchHref('status', app),
    };
  }

  return {
    label: 'Let Foxhound keep tracking',
    detail: 'Foxhound is monitoring the posting, preparing context, and will flag the next meaningful action.',
    href: app.brief_ready ? `/brief/${app.id}` : researchHref('brief', app),
  };
}

function shouldOfferArchive(app: AppItem): boolean {
  if (app.status === 'canceled') return false;
  if (app.posting_status === 'removed') return true;
  const age = daysSince(app.submitted_at || app.created_at);
  return typeof age === 'number' && age >= 14;
}

/* ─── Sub-components ─── */

function PostingStatusBadge({ postingStatus }: { postingStatus?: string | null }) {
  const status = (postingStatus || 'unknown') as PostingStatus;
  const cfg = POSTING_STATUS_CONFIG[status] || POSTING_STATUS_CONFIG.unknown;

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: cfg.color,
          flexShrink: 0,
          boxShadow: status !== 'unknown' ? `0 0 5px ${cfg.color}40` : 'none',
        }}
        aria-hidden="true"
      />
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: cfg.color, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
        {cfg.label}
      </span>
    </span>
  );
}

function ViewToggle({ view, onChange }: { view: ViewMode; onChange: (v: ViewMode) => void }) {
  return (
    <div style={{ display: 'inline-flex', border: '1px solid var(--b)', borderRadius: 6, overflow: 'hidden' }} role="group" aria-label="View mode">
      <button
        onClick={() => onChange('list')}
        aria-label="List view"
        aria-pressed={view === 'list'}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 34, height: 30, border: 'none', cursor: 'pointer',
          background: view === 'list' ? 'var(--vf)' : 'transparent',
          color: view === 'list' ? 'var(--vl)' : 'var(--t3)',
          transition: 'all 0.2s',
          borderRight: '1px solid var(--b)',
        }}
      >
        {/* List icon */}
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <rect x="1" y="2" width="12" height="1.5" rx="0.5" fill="currentColor" />
          <rect x="1" y="6.25" width="12" height="1.5" rx="0.5" fill="currentColor" />
          <rect x="1" y="10.5" width="12" height="1.5" rx="0.5" fill="currentColor" />
        </svg>
      </button>
      <button
        onClick={() => onChange('kanban')}
        aria-label="Kanban view"
        aria-pressed={view === 'kanban'}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 34, height: 30, border: 'none', cursor: 'pointer',
          background: view === 'kanban' ? 'var(--vf)' : 'transparent',
          color: view === 'kanban' ? 'var(--vl)' : 'var(--t3)',
          transition: 'all 0.2s',
        }}
      >
        {/* Kanban icon */}
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <rect x="1" y="1" width="3.5" height="12" rx="1" fill="currentColor" />
          <rect x="5.25" y="1" width="3.5" height="8" rx="1" fill="currentColor" />
          <rect x="9.5" y="1" width="3.5" height="10" rx="1" fill="currentColor" />
        </svg>
      </button>
    </div>
  );
}

function CheckNowButton({ appId, onChecked }: { appId: string; onChecked?: () => void }) {
  const [checking, setChecking] = useState(false);
  const [done, setDone] = useState(false);

  const handleClick = useCallback(async () => {
    if (checking || done) return;
    setChecking(true);
    try {
      await triggerWatchdogCheck(appId);
      setDone(true);
      onChecked?.();
      setTimeout(() => setDone(false), 3000);
    } catch {
      /* fail silently — watchdog is best-effort */
    } finally {
      setChecking(false);
    }
  }, [appId, checking, done, onChecked]);

  return (
    <button
      onClick={handleClick}
      disabled={checking}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        padding: '4px 10px',
        border: '1px solid var(--b)',
        borderRadius: 4,
        background: 'transparent',
        color: done ? 'var(--g)' : checking ? 'var(--t3)' : 'var(--t3)',
        cursor: checking ? 'wait' : 'pointer',
        transition: 'all 0.2s',
        whiteSpace: 'nowrap',
        minHeight: 28,
      }}
      onMouseEnter={(e) => { if (!checking && !done) { e.currentTarget.style.borderColor = 'var(--bv)'; e.currentTarget.style.color = 'var(--vl)'; }}}
      onMouseLeave={(e) => { if (!checking && !done) { e.currentTarget.style.borderColor = 'var(--b)'; e.currentTarget.style.color = 'var(--t3)'; }}}
      aria-label="Verify if this job posting is still active"
      title="Check if the posting is still live, edited, or removed"
    >
      {done ? 'Queued' : checking ? '...' : 'Check Status'}
    </button>
  );
}

/* ─── Screenshot Lightbox ─── */

function ScreenshotLightbox({ url, company, onClose }: { url: string; company: string; onClose: () => void }) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      role="dialog"
      aria-label={`Screenshot for ${company}`}
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 300,
        background: 'rgba(0, 0, 0, 0.82)',
        backdropFilter: 'blur(12px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        animation: 'lightbox-in 0.2s ease-out',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'relative',
          maxWidth: 900,
          width: '100%',
          maxHeight: '85vh',
        }}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          aria-label="Close screenshot"
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
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.14)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; }}
        >
          &times;
        </button>

        {/* Screenshot image */}
        <div style={{ position: 'relative', width: '100%', height: '80vh', maxHeight: '80vh' }}>
          <Image
            src={url}
            alt={`Application screenshot for ${company}`}
            fill
            unoptimized
            sizes="(max-width: 900px) 100vw, 900px"
            style={{
              objectFit: 'contain',
              borderRadius: 10,
              border: '1px solid var(--b)',
            }}
          />
        </div>

        {/* Caption */}
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--t3)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          textAlign: 'center',
          marginTop: 12,
        }}>
          Submission receipt -- {company}
        </div>
      </div>
    </div>
  );
}

function ScreenshotThumbnail({ url, company, onClick }: { url: string; company: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-label={`View screenshot for ${company}`}
      title="View submission screenshot"
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
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--bv)';
        e.currentTarget.style.boxShadow = '0 0 10px rgba(139,92,246,0.12)';
        const image = e.currentTarget.querySelector('img');
        if (image) {
          (image as HTMLImageElement).style.opacity = '1';
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--b)';
        e.currentTarget.style.boxShadow = 'none';
        const image = e.currentTarget.querySelector('img');
        if (image) {
          (image as HTMLImageElement).style.opacity = '0.7';
        }
      }}
    >
      <Image
        src={url}
        alt=""
        aria-hidden="true"
        fill
        unoptimized
        sizes="48px"
        style={{
          objectFit: 'cover',
          display: 'block',
          opacity: 0.7,
          transition: 'opacity 0.2s',
        }}
      />
      {/* Expand indicator */}
      <span style={{
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
      }}>
        <svg width="7" height="7" viewBox="0 0 7 7" fill="none" aria-hidden="true">
          <path d="M0 0H3V1H1V3H0V0Z" fill="rgba(255,255,255,0.6)" />
          <path d="M7 7H4V6H6V4H7V7Z" fill="rgba(255,255,255,0.6)" />
        </svg>
      </span>
    </button>
  );
}

/* ─── Kanban Column ─── */

function KanbanColumn({ title, apps, color }: { title: string; apps: AppItem[]; color: string }) {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      {/* Column header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '10px 12px', marginBottom: 8,
        borderBottom: `2px solid ${color}20`,
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0,
          boxShadow: `0 0 6px ${color}40`,
        }} aria-hidden="true" />
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500,
          letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--t)',
        }}>
          {title}
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--t3)', marginLeft: 'auto',
        }}>
          {apps.length}
        </span>
      </div>

      {/* Cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {apps.length > 0 ? apps.map((app) => {
          const cfg = STATUS_CONFIG[app.status] || { color: 'var(--t3)', label: app.status };
          return (
            <div
              key={app.id}
              style={{
                background: 'var(--sf)',
                border: '1px solid var(--b)',
                borderRadius: 8,
                padding: '12px 14px',
                transition: 'border-color 0.2s, transform 0.2s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--bv)'; e.currentTarget.style.transform = 'translateY(-1px)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--b)'; e.currentTarget.style.transform = ''; }}
            >
              {/* Company and role */}
              <div style={{
                fontSize: 13, fontWeight: 500, color: 'var(--t)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {app.job.company}
              </div>
              <div style={{
                fontSize: 12, color: 'var(--t2)', marginTop: 2,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {app.job.title}
              </div>

              {/* Meta row: days + status badge */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                marginTop: 10, flexWrap: 'wrap',
              }}>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10,
                  color: 'var(--t3)', letterSpacing: '0.04em',
                }}>
                  {daysAgo(app.created_at)}
                </span>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
                  padding: '2px 7px', borderRadius: 3,
                  background: `${cfg.color}15`, color: cfg.color,
                  textTransform: 'uppercase', letterSpacing: '0.04em',
                }}>
                  {cfg.label}
                </span>
              </div>

              {/* Posting status + action buttons */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginTop: 10, paddingTop: 8,
                borderTop: '1px solid var(--b)',
                gap: 6, flexWrap: 'wrap',
              }}>
                <PostingStatusBadge postingStatus={app.posting_status} />
              </div>
            </div>
          );
        }) : (
          <div style={{
            padding: '24px 14px', textAlign: 'center',
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--t3)', letterSpacing: '0.06em', textTransform: 'uppercase',
            background: 'var(--sf)', border: '1px dashed var(--b)', borderRadius: 8,
          }}>
            None
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Kanban View ─── */

function KanbanView({ apps }: { apps: AppItem[] }) {
  const grouped: Record<string, AppItem[]> = { unknown: [], active: [], edited: [], removed: [] };

  apps.forEach((app) => {
    const ps = app.posting_status || 'unknown';
    // Reposted goes into Active column
    const bucket = ps === 'reposted' ? 'active' : ps;
    if (grouped[bucket]) {
      grouped[bucket].push(app);
    } else {
      grouped.unknown.push(app);
    }
  });

  return (
    <div className="kanban-grid" style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 12,
      background: 'var(--sf)',
      border: '1px solid var(--b)',
      borderRadius: 12,
      padding: 12,
    }}>
      {KANBAN_COLUMNS.map((col) => (
        <KanbanColumn
          key={col.key}
          title={col.title}
          apps={grouped[col.key] || []}
          color={POSTING_STATUS_CONFIG[col.key].color}
        />
      ))}
    </div>
  );
}

function ManualTrackPanel({
  defaultOpen = false,
  onTracked,
}: {
  defaultOpen?: boolean;
  onTracked: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    company: '',
    title: '',
    apply_url: '',
    location: '',
    notes: '',
  });

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!form.company.trim() || !form.title.trim() || !form.apply_url.trim()) {
      setError('Company, title, and application URL are required.');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      await trackManualApplication({
        company: form.company.trim(),
        title: form.title.trim(),
        apply_url: form.apply_url.trim(),
        location: form.location.trim() || undefined,
        notes: form.notes.trim() || undefined,
      });
      setForm({ company: '', title: '', apply_url: '', location: '', notes: '' });
      setOpen(false);
      await onTracked();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not track this application.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{
      marginTop: 20,
      background: 'var(--sf)',
      border: '1px solid var(--b)',
      borderRadius: 12,
      overflow: 'hidden',
    }}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '16px 18px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <div>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--vl)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            marginBottom: 6,
          }}>
            Manual Tracking
          </div>
          <div style={{ fontSize: 14, color: 'var(--t2)', lineHeight: 1.6 }}>
            Already applied somewhere else? Add it here and Foxhound will keep tracking the posting, people, and follow-up timing.
          </div>
        </div>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--t3)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          whiteSpace: 'nowrap',
        }}>
          {open ? 'Close' : 'Track manually'}
        </span>
      </button>

      {open && (
        <form onSubmit={handleSubmit} style={{
          borderTop: '1px solid var(--b)',
          padding: 18,
          display: 'grid',
          gap: 10,
        }}>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <input
              className="input"
              placeholder="Company"
              value={form.company}
              onChange={(e) => setForm((current) => ({ ...current, company: e.target.value }))}
              disabled={submitting}
            />
            <input
              className="input"
              placeholder="Role title"
              value={form.title}
              onChange={(e) => setForm((current) => ({ ...current, title: e.target.value }))}
              disabled={submitting}
            />
          </div>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <input
              className="input"
              placeholder="Application URL"
              value={form.apply_url}
              onChange={(e) => setForm((current) => ({ ...current, apply_url: e.target.value }))}
              disabled={submitting}
            />
            <input
              className="input"
              placeholder="Location (optional)"
              value={form.location}
              onChange={(e) => setForm((current) => ({ ...current, location: e.target.value }))}
              disabled={submitting}
            />
          </div>
          <textarea
            className="input"
            placeholder="Notes (optional): where you applied, who referred you, or anything Foxhound should remember"
            value={form.notes}
            onChange={(e) => setForm((current) => ({ ...current, notes: e.target.value }))}
            disabled={submitting}
            rows={3}
            style={{ resize: 'vertical', minHeight: 96 }}
          />
          {error && (
            <div style={{ fontSize: 12, color: 'var(--error)', lineHeight: 1.6 }}>
              {error}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="submit" className="btn-violet" disabled={submitting}>
              {submitting ? 'Tracking...' : 'Track Application'}
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/* ─── Main Page ─── */

export default function ApplicationsPage() {
  const [apps, setApps] = useState<AppItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [stats, setStats] = useState<Record<string, number>>({});
  const [view, setView] = useState<ViewMode>('list');
  const [lightbox, setLightbox] = useState<{ url: string; company: string } | null>(null);
  const [archivingId, setArchivingId] = useState<string | null>(null);

  const loadApplications = useCallback(async () => {
    const data = await listApplications({ per_page: 50 });
    setApps(data.items);
    const s: Record<string, number> = {};
    data.items.forEach((a) => { s[a.status] = (s[a.status] || 0) + 1; });
    setStats(s);
  }, []);

  useEffect(() => {
    loadApplications()
      .catch(() => { /* API unavailable — empty state */ })
      .finally(() => setLoading(false));
  }, [loadApplications]);

  const filtered = filter === 'all' ? apps : apps.filter(a => a.status === filter);

  if (loading) {
    return (
      <AuthGuard>
        <AppNav />
        <PageSkeleton variant="list" />
      </AuthGuard>
    );
  }

  return (
    <AuthGuard>
      <AppNav />
      <main style={{
        paddingTop: 80,
        maxWidth: view === 'kanban' ? 1100 : 900,
        margin: '0 auto',
        padding: '80px 20px 140px',
        position: 'relative',
        zIndex: 1,
        transition: 'max-width 0.3s ease',
      }}>
        <ScrollReveal>
          <div className="section-label">Applications</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', margin: 0 }}>
              {apps.length > 0 ? `${apps.length} Tracked` : 'No Applications Yet'}
            </h1>
            {apps.length > 0 && <ViewToggle view={view} onChange={setView} />}
          </div>
          <p style={{
            margin: '14px 0 0',
            maxWidth: 760,
            fontSize: 14,
            lineHeight: 1.7,
            color: 'var(--t3)',
          }}>
            Foxhound keeps working after every application — monitoring posting status, researching companies, finding contacts, and scheduling follow-ups. Open a brief for the full picture on any role, or add a role you already applied to so Foxhound can track that too.
          </p>
          <div style={{ display: 'flex', gap: 10, marginTop: 18, flexWrap: 'wrap' }}>
            <Link href="/jobs" className="btn-violet">Browse Jobs</Link>
            <Link href="/intelligence" className="btn-ghost">Open Research</Link>
          </div>
        </ScrollReveal>

        <ManualTrackPanel defaultOpen={apps.length === 0} onTracked={loadApplications} />

        {apps.length > 0 && (
          <ScrollReveal delay={1}>
            <div style={{
              marginTop: 24,
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: 10,
            }}>
              {[
                {
                  label: 'Monitoring',
                  detail: 'Foxhound keeps checking live postings and flags edits, removals, or reposts.',
                },
                {
                  label: 'Follow-up',
                  detail: 'Foxhound tracks the day 3 / 7 / 14 windows and tells you when it is time to follow up.',
                },
                {
                  label: 'Interview Prep',
                  detail: 'When an interview is detected, Foxhound runs prep automatically — questions, salary data, and company deep-dive.',
                },
                {
                  label: 'Manual Tracking',
                  detail: 'Already applied somewhere else? Add it here so Foxhound can still monitor the role and coach the process.',
                },
              ].map((item) => (
                <div key={item.label} style={{
                  background: 'var(--sf)',
                  border: '1px solid var(--b)',
                  borderRadius: 10,
                  padding: '14px 16px',
                }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                    {item.label}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--t3)', lineHeight: 1.6, marginTop: 8 }}>
                    {item.detail}
                  </div>
                </div>
              ))}
            </div>
          </ScrollReveal>
        )}

        {/* Filter chips — only show when there are apps and in list view */}
        {apps.length > 0 && view === 'list' && (
          <ScrollReveal delay={1}>
            <div style={{ display: 'flex', gap: 8, marginTop: 24, marginBottom: 24, flexWrap: 'wrap' }}>
              {[{ key: 'all', label: `All (${apps.length})` }, ...Object.entries(stats).map(([k, v]) => ({ key: k, label: `${STATUS_CONFIG[k]?.label || k} (${v})` }))].map(f => (
                <button key={f.key} onClick={() => setFilter(f.key)} style={{
                  fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase', padding: '8px 16px',
                  border: `1px solid ${filter === f.key ? 'var(--bv)' : 'var(--b)'}`, borderRadius: 6, cursor: 'pointer',
                  background: filter === f.key ? 'var(--vf)' : 'transparent', color: filter === f.key ? 'var(--vl)' : 'var(--t3)', transition: 'all 0.2s',
                }}>
                  {f.label}
                </button>
              ))}
            </div>
          </ScrollReveal>
        )}

        {/* View content */}
        <ScrollReveal delay={2}>
          {view === 'kanban' ? (
            <div style={{ marginTop: 24 }}>
              <KanbanView apps={filtered} />
            </div>
          ) : (
            /* ─── List View ─── */
            <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, overflow: 'hidden', marginBottom: 20 }}>
              {filtered.length > 0 ? (
                filtered.map((app, i) => {
                  const cfg = STATUS_CONFIG[app.status] || { color: 'var(--t3)', label: app.status };
                  const isPulsing = (cfg as typeof cfg & { pulse?: boolean }).pulse;
                  const nextStep = nextStepForApplication(app);
                  const canArchive = shouldOfferArchive(app);
                  return (
                    <div key={app.id || i} style={{
                      display: 'grid', gridTemplateColumns: '3px 1fr', gap: '0 16px',
                      padding: '18px 20px 18px 0', borderBottom: '1px solid var(--b)', transition: 'background 0.15s',
                    }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(139,92,246,0.02)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = '')}
                    >
                      {/* Left accent bar */}
                      <div style={{ width: 3, borderRadius: 2, alignSelf: 'stretch', background: cfg.color }} />

                      {/* Card content */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: 0 }}>
                        {/* Row 1: Header -- title + badges + thumbnail */}
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                          {/* Left: title block */}
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{
                              fontFamily: 'var(--font-display)',
                              fontSize: 15,
                              fontWeight: 600,
                              letterSpacing: '-0.01em',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              color: 'var(--t)',
                            }}>
                              {app.job.title}
                            </div>
                            <div style={{
                              fontSize: 13,
                              color: 'var(--t2)',
                              marginTop: 2,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}>
                              {app.job.company}
                            </div>
                            {/* Meta: date, actor */}
                            <div style={{
                              fontFamily: 'var(--font-mono)',
                              fontSize: 10,
                              color: 'var(--t3)',
                              marginTop: 6,
                              display: 'flex',
                              gap: 10,
                              alignItems: 'center',
                              flexWrap: 'wrap',
                              letterSpacing: '0.04em',
                            }}>
                              <span>{app.created_at ? new Date(app.created_at).toLocaleDateString() : ''}</span>
                              <span>{runActorLabel(app.trigger)}</span>
                            </div>
                          </div>

                          {/* Right: badges + thumbnail */}
                          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, flexShrink: 0 }}>
                            {/* Status badge */}
                            <span
                              className={isPulsing ? 'app-status-pulse' : undefined}
                              style={{
                                fontFamily: 'var(--font-mono)',
                                fontSize: 10,
                                fontWeight: 600,
                                padding: '3px 10px',
                                borderRadius: 4,
                                background: `${cfg.color}15`,
                                color: cfg.color,
                                textTransform: 'uppercase',
                                letterSpacing: '0.04em',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {cfg.label}
                            </span>
                            {/* Screenshot thumbnail */}
                            {app.screenshot_url && (
                              <ScreenshotThumbnail
                                url={app.screenshot_url}
                                company={app.job.company}
                                onClick={() => setLightbox({ url: app.screenshot_url!, company: app.job.company })}
                              />
                            )}
                          </div>
                        </div>

                        {/* Row 2: Actions -- posting status + buttons */}
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: 8,
                          marginTop: 12,
                          paddingTop: 10,
                          borderTop: '1px solid var(--b)',
                          flexWrap: 'wrap',
                        }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <PostingStatusBadge postingStatus={app.posting_status} />
                            {(app.last_watchdog_check_at || app.posting_diff_summary) && (
                              <div style={{ fontSize: 11, color: 'var(--t3)', lineHeight: 1.6 }}>
                                {app.last_watchdog_check_at && (
                                  <div>
                                    Last checked {new Date(app.last_watchdog_check_at).toLocaleDateString()}
                                  </div>
                                )}
                                {app.posting_diff_summary && <div>{app.posting_diff_summary}</div>}
                              </div>
                            )}
                            <div style={{ fontSize: 12, color: 'var(--t3)', lineHeight: 1.6 }}>
                              {app.status === 'canceled'
                                ? 'Foxhound has archived this role from the active queue, but you can still reopen the brief or research context.'
                                : app.status === 'submitted'
                                ? app.brief_ready
                                  ? 'Foxhound is tracking the posting and has already assembled a brief you can revisit anytime.'
                                  : 'Foxhound is tracking the posting and preparing the next layer of research.'
                                : app.status === 'waiting_user_input'
                                  ? 'Foxhound is paused on this application until you answer the remaining questions.'
                                  : app.status === 'needs_manual'
                                    ? 'Foxhound hit an edge case here and needs a manual handoff.'
                                    : 'Foxhound is still processing this application.'}
                            </div>
                          </div>
                          <div style={{ display: 'flex', gap: 6, marginLeft: 'auto', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                            <CheckNowButton appId={app.id} />
                            <Link href={`/brief/${app.id}`} style={{
                              fontFamily: 'var(--font-mono)', fontSize: 10,
                              letterSpacing: '0.04em', textTransform: 'uppercase',
                              padding: '4px 10px', borderRadius: 4,
                              border: '1px solid var(--bv)', color: 'var(--vl)',
                              display: 'inline-flex', alignItems: 'center',
                              minHeight: 28, whiteSpace: 'nowrap',
                            }}>
                              View Brief
                            </Link>
                            {canArchive && (
                              <button
                                type="button"
                                onClick={async () => {
                                  if (archivingId) return;
                                  setArchivingId(app.id);
                                  try {
                                    await archiveApplication(app.id);
                                    await loadApplications();
                                  } finally {
                                    setArchivingId(null);
                                  }
                                }}
                                style={{
                                  fontFamily: 'var(--font-mono)', fontSize: 10,
                                  letterSpacing: '0.04em', textTransform: 'uppercase',
                                  padding: '4px 10px', borderRadius: 4,
                                  border: '1px solid rgba(248,113,113,0.18)', color: 'var(--error)',
                                  background: 'transparent',
                                  display: 'inline-flex', alignItems: 'center',
                                  minHeight: 28, whiteSpace: 'nowrap',
                                  cursor: archivingId ? 'wait' : 'pointer',
                                  opacity: archivingId === app.id ? 0.7 : 1,
                                }}
                              >
                                {archivingId === app.id ? 'Archiving...' : 'Archive'}
                              </button>
                            )}
                          </div>
                        </div>

                        <div style={{
                          marginTop: 10,
                          paddingTop: 10,
                          borderTop: '1px dashed rgba(255,255,255,0.08)',
                          display: 'flex',
                          alignItems: 'flex-start',
                          justifyContent: 'space-between',
                          gap: 12,
                          flexWrap: 'wrap',
                        }}>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{
                              fontFamily: 'var(--font-mono)',
                              fontSize: 10,
                              color: 'var(--vl)',
                              letterSpacing: '0.08em',
                              textTransform: 'uppercase',
                              marginBottom: 6,
                            }}>
                              Next Step
                            </div>
                            <div style={{ fontSize: 13, color: 'var(--t2)', fontWeight: 500 }}>
                              {nextStep.label}
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--t3)', lineHeight: 1.6, marginTop: 4 }}>
                              {nextStep.detail}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div style={{ padding: '64px 32px', textAlign: 'center' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t3)', marginBottom: 16 }}>
                    {filter === 'all' ? 'No applications yet' : `No ${STATUS_CONFIG[filter]?.label || filter} applications`}
                  </div>
                  {filter === 'all' && (
                    <div style={{ display: 'inline-flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
                      <Link href="/jobs" className="btn-violet">Browse Jobs &#8594;</Link>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </ScrollReveal>

        {/* ─── Responsive overrides for kanban on mobile ─── */}
        <style>{`
          @media (max-width: 768px) {
            .kanban-grid {
              grid-template-columns: 1fr !important;
              gap: 20px !important;
            }
          }
          @keyframes lightbox-in {
            from { opacity: 0; }
            to { opacity: 1; }
          }
          @keyframes app-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
          }
          .app-status-pulse {
            animation: app-pulse 2s ease-in-out infinite;
          }
          @media (prefers-reduced-motion: reduce) {
            .app-status-pulse { animation: none; }
          }
        `}</style>
      </main>

      {/* Screenshot lightbox */}
      {lightbox && (
        <ScreenshotLightbox
          url={lightbox.url}
          company={lightbox.company}
          onClose={() => setLightbox(null)}
        />
      )}
    </AuthGuard>
  );
}
