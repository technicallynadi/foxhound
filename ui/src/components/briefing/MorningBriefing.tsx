'use client';

import { useState } from 'react';
import Link from 'next/link';

interface BriefingApp {
  application_id: string;
  company: string;
  title: string;
  match_score: number | null;
  submitted_at: string | null;
  status: string;
  brief_ready: boolean;
  brief_id: string | null;
}

interface BriefingAlert {
  type: string;
  title: string;
  description: string;
}

interface BriefingMatch {
  match_id: string;
  job_id: string;
  company: string;
  title: string;
  match_score: number;
}

interface MorningBriefingProps {
  generatedAt?: string;
  summary: {
    jobs_discovered: number;
    matches_above_threshold: number;
    applications_submitted: number;
    alerts_count: number;
    questions_pending: number;
  };
  applications: BriefingApp[];
  alerts: BriefingAlert[];
  newMatches: BriefingMatch[];
  onApply?: (jobId: string) => void;
  onDismissMatch?: (matchId: string) => void;
}

const mono = { fontFamily: 'var(--font-mono)' };

export default function MorningBriefing({ generatedAt, summary, applications, alerts, newMatches, onApply, onDismissMatch }: MorningBriefingProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const hasContent = summary.applications_submitted > 0 || summary.alerts_count > 0 || summary.matches_above_threshold > 0;
  if (!hasContent) {
    // Empty state — agent is scanning
    return (
      <div style={{
        background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
        padding: 24, marginTop: 24,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ ...mono, fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            FOXHOUND STATUS
          </span>
          <span style={{
            ...mono, fontSize: 10, color: 'var(--g)', textTransform: 'uppercase',
            display: 'inline-flex', alignItems: 'center', gap: 4,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--g)', animation: 'pulse 2s infinite' }} />
            Active
          </span>
        </div>
        <p style={{ fontSize: 14, color: 'var(--t3)', marginTop: 12 }}>
          Nothing new overnight. Foxhound is still looking for matches.
        </p>
      </div>
    );
  }

  return (
    <div style={{
      background: 'var(--sf)', border: '1px solid var(--bv)', borderRadius: 12,
      padding: 24, marginTop: 24,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <span style={{ ...mono, fontSize: 11, color: 'var(--vl)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            MORNING BRIEFING
          </span>
          <div style={{ ...mono, fontSize: 10, color: 'var(--t3)', marginTop: 4 }}>
            Here is what happened while you were away
            {generatedAt && ` · updated ${new Date(generatedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`}
          </div>
        </div>
        <button
          onClick={() => setDismissed(true)}
          style={{
            ...mono, fontSize: 10, color: 'var(--t3)', textTransform: 'uppercase',
            background: 'none', border: 'none', cursor: 'pointer',
          }}
        >
          Dismiss
        </button>
      </div>

      {/* Summary line */}
      <div style={{ ...mono, fontSize: 12, color: 'var(--t2)', marginBottom: 20, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <span><b>{summary.jobs_discovered}</b> jobs found</span>
        <span style={{ color: 'var(--t3)' }}>&middot;</span>
        <span><b>{summary.matches_above_threshold}</b> strong fits</span>
        <span style={{ color: 'var(--t3)' }}>&middot;</span>
        <span><b>{summary.applications_submitted}</b> applied</span>
        {summary.questions_pending > 0 && (
          <>
            <span style={{ color: 'var(--t3)' }}>&middot;</span>
            <span><b>{summary.questions_pending}</b> waiting on you</span>
          </>
        )}
        {summary.alerts_count > 0 && (
          <>
            <span style={{ color: 'var(--t3)' }}>&middot;</span>
            <span><b>{summary.alerts_count}</b> alert{summary.alerts_count !== 1 ? 's' : ''}</span>
          </>
        )}
      </div>

      {/* Applied section */}
      {applications.length > 0 && (
        <Section label="APPLIED">
          {applications.map((app) => (
            <div key={app.application_id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '10px 0', borderBottom: '1px solid var(--b)',
            }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {app.company} — {app.title}
                </div>
                <div style={{ ...mono, fontSize: 11, color: 'var(--t3)', marginTop: 2 }}>
                  {app.submitted_at ? `Submitted ${new Date(app.submitted_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}` : app.status.replace(/_/g, ' ')}
                  {app.brief_ready && ' · Brief ready'}
                  {app.status === 'waiting_user_input' && ` · Needs your answers`}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0, marginLeft: 12 }}>
                {app.match_score && (
                  <span style={{
                    ...mono, fontSize: 14, fontWeight: 700,
                    color: app.match_score >= 80 ? 'var(--g)' : app.match_score >= 70 ? 'var(--vl)' : 'var(--t3)',
                  }}>
                    {app.match_score}%
                  </span>
                )}
                {app.brief_ready && (
                  <Link href={`/brief/${app.application_id}`} style={{
                    ...mono, fontSize: 10, color: 'var(--vl)', textTransform: 'uppercase',
                    letterSpacing: '0.04em', padding: '4px 10px', borderRadius: 4,
                    border: '1px solid var(--bv)',
                  }}>
                    View Brief
                  </Link>
                )}
              </div>
            </div>
          ))}
        </Section>
      )}

      {/* Alerts section */}
      {alerts.length > 0 && (
        <Section label="ALERTS">
          {alerts.map((alert, i) => (
            <div key={i} style={{ padding: '8px 0', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <span style={{
                ...mono, fontSize: 12, marginTop: 2,
                color: alert.type === 'ghost_alert' ? 'var(--error)' : alert.type.includes('followup') ? 'var(--warning)' : 'var(--vl)',
              }}>
                {alert.type === 'ghost_alert' ? '!' : alert.type.includes('followup') ? '@' : '*'}
              </span>
              <div>
                <div style={{ fontSize: 14 }}>{alert.title}</div>
                {alert.description && <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>{alert.description}</div>}
              </div>
            </div>
          ))}
        </Section>
      )}

      {/* New matches section */}
      {newMatches.length > 0 && (
        <Section label="NEW MATCHES">
          {newMatches.map((match) => (
            <div key={match.match_id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 0', borderBottom: '1px solid var(--b)',
            }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <span style={{ fontSize: 14, fontWeight: 500 }}>
                  {match.company} — {match.title}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, marginLeft: 12 }}>
                <span style={{
                  ...mono, fontSize: 14, fontWeight: 700,
                  color: match.match_score >= 80 ? 'var(--g)' : 'var(--vl)',
                }}>
                  {match.match_score}%
                </span>
                {onApply && (
                  <button onClick={() => onApply(match.job_id)} style={{
                    ...mono, fontSize: 10, color: 'var(--vl)', textTransform: 'uppercase',
                    letterSpacing: '0.04em', padding: '4px 10px', borderRadius: 4,
                    border: '1px solid var(--bv)', background: 'transparent', cursor: 'pointer',
                  }}>
                    Apply
                  </button>
                )}
                {onDismissMatch && (
                  <button onClick={() => onDismissMatch(match.match_id)} style={{
                    ...mono, fontSize: 10, color: 'var(--t3)', textTransform: 'uppercase',
                    background: 'none', border: 'none', cursor: 'pointer',
                  }}>
                    Skip
                  </button>
                )}
              </div>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8,
      padding: 16, marginTop: 12,
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)',
        textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8,
      }}>
        {label}
      </div>
      {children}
    </div>
  );
}
