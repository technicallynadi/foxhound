'use client';

import Link from 'next/link';

interface Props {
  toolName: string;
  data: Record<string, unknown>;
}

export default function ToolResultCard({ toolName, data }: Props) {
  if (toolName === 'search_jobs' || toolName === 'get_matches') {
    const items = (data.jobs || data.matches || []) as Array<Record<string, unknown>>;
    if (items.length === 0) return null;

    return (
      <div style={{ padding: '3px 0' }}>
        <div className="glass-panel" style={{ padding: 10, borderRadius: 12 }}>
          {items.slice(0, 5).map((item, i) => (
            <div key={item.job_id as string || i} style={{
              padding: '7px 0',
              borderBottom: i < Math.min(items.length, 5) - 1 ? '1px solid var(--glass-border)' : 'none',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{item.title as string}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                  {item.company as string} — {item.location as string}
                </div>
              </div>
              {item.match_score != null && (
                <span style={{
                  fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
                  background: `${scoreColor(item.match_score as number)}18`,
                  color: scoreColor(item.match_score as number),
                }}>
                  {item.match_score as number}%
                </span>
              )}
            </div>
          ))}
          {items.length > 5 && (
            <Link href="/jobs" style={{
              display: 'block', textAlign: 'center', padding: '8px 0 2px',
              fontSize: 12, color: 'var(--accent-blue)',
            }}>
              View all {items.length} results
            </Link>
          )}
        </div>
      </div>
    );
  }

  if (toolName === 'apply_to_job' || toolName === 'check_application_status') {
    const status = data.status as string;
    const company = data.company as string;
    const title = (data.job_title || data.title || '') as string;
    const questions = (data.pending_questions || []) as Array<Record<string, unknown>>;

    return (
      <div style={{ padding: '3px 0' }}>
        <div className="glass-panel" style={{
          padding: 10, borderRadius: 12,
          borderLeft: `3px solid ${statusColor(status)}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{company}{title ? ` — ${title}` : ''}</div>
              <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 1 }}>{statusLabel(status)}</div>
            </div>
            <StatusBadge status={status} />
          </div>
          {questions.length > 0 && (
            <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--glass-border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4 }}>
                {questions.length} question{questions.length > 1 ? 's' : ''} need your input:
              </div>
              {questions.map((q, i) => (
                <div key={i} style={{ padding: '4px 0' }}>
                  <div style={{ fontSize: 12, color: '#fff' }}>{String(q.index)}. {String(q.question)}</div>
                  {q.suggested_answer ? (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1, fontStyle: 'italic' }}>
                      Draft: {String(q.suggested_answer).slice(0, 80)}...
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (toolName === 'get_applications') {
    const apps = (data.applications || []) as Array<Record<string, unknown>>;
    if (apps.length === 0) return null;
    return (
      <div style={{ padding: '3px 0' }}>
        <div className="glass-panel" style={{ padding: 10, borderRadius: 12 }}>
          {apps.slice(0, 5).map((app, i) => (
            <div key={app.application_id as string || i} style={{
              padding: '5px 0',
              borderBottom: i < Math.min(apps.length, 5) - 1 ? '1px solid var(--glass-border)' : 'none',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12,
            }}>
              <span>{app.company as string} — {app.title as string}</span>
              <StatusBadge status={app.status as string} />
            </div>
          ))}
          <Link href="/applications" style={{
            display: 'block', textAlign: 'center', padding: '6px 0 0',
            fontSize: 12, color: 'var(--accent-blue)',
          }}>
            View all in tracker
          </Link>
        </div>
      </div>
    );
  }

  if (toolName === 'get_profile') {
    return (
      <div style={{ padding: '3px 0' }}>
        <div className="glass-panel" style={{ padding: 10, borderRadius: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{data.name as string}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 1 }}>
            {data.location as string} — {data.tier as string} tier
          </div>
          {Array.isArray(data.skills) && (
            <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {(data.skills as string[]).slice(0, 6).map((s) => (
                <span key={s} style={{
                  background: 'rgba(255,255,255,0.05)', border: '1px solid var(--glass-border)',
                  borderRadius: 5, padding: '1px 6px', fontSize: 11, color: 'var(--text-muted)',
                }}>{s}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (toolName === 'update_preferences' && data.changes) {
    return (
      <div style={{ padding: '3px 0', fontSize: 12, color: 'var(--color-success)' }}>
        Updated: {(data.changes as string[]).join(', ')}
      </div>
    );
  }

  return null;
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 99,
      background: `${statusColor(status)}18`, color: statusColor(status),
      textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function statusColor(s: string): string {
  if (s === 'submitted') return 'var(--color-success)';
  if (s === 'scanning' || s === 'in_progress') return 'var(--accent-blue)';
  if (s === 'waiting_user_input' || s === 'needs_manual') return '#f59e0b';
  if (s === 'failed') return 'var(--color-error)';
  return 'var(--text-muted)';
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    scanning: 'Scanning form...', in_progress: 'Filling application...',
    submitted: 'Submitted', waiting_user_input: 'Needs your input',
    failed: 'Failed', needs_manual: 'Manual needed',
  };
  if (!s) return 'Unknown';
  return map[s] || s.replace(/_/g, ' ');
}

function scoreColor(n: number): string {
  if (n >= 85) return 'var(--color-success)';
  if (n >= 70) return '#f59e0b';
  return 'var(--text-muted)';
}
