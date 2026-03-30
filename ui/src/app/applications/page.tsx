'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import ScrollReveal from '@/components/landing/ScrollReveal';
import { listApplications } from '@/lib/api';

interface AppItem {
  id: string;
  status: string;
  trigger: string;
  job: { id: string; title: string; company: string; ats_type: string };
  tinyfish_status: string | null;
  screenshot_url: string | null;
  submitted_at: string | null;
  created_at: string | null;
}

const STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  submitted: { color: 'var(--g)', label: 'Submitted' },
  scanning: { color: 'var(--vl)', label: 'Scanning' },
  in_progress: { color: 'var(--vl)', label: 'In Progress' },
  waiting_user_input: { color: 'var(--warning)', label: 'Needs Input' },
  failed: { color: 'var(--error)', label: 'Failed' },
  needs_manual: { color: 'var(--warning)', label: 'Manual' },
  canceled: { color: 'var(--t3)', label: 'Canceled' },
};

const LIFECYCLE = ['applied', 'viewed', 'interview', 'offer'];

export default function ApplicationsPage() {
  const [apps, setApps] = useState<AppItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [stats, setStats] = useState<Record<string, number>>({});

  useEffect(() => {
    listApplications({ per_page: 50 })
      .then(data => {
        setApps(data.items);
        const s: Record<string, number> = {};
        data.items.forEach((a) => { s[a.status] = (s[a.status] || 0) + 1; });
        setStats(s);
      })
      .catch(() => { /* API unavailable — empty state */ })
      .finally(() => setLoading(false));
  }, []);

  const filtered = filter === 'all' ? apps : apps.filter(a => a.status === filter);

  return (
    <AuthGuard>
      <AppNav />
      <main style={{ paddingTop: 80, maxWidth: 900, margin: '0 auto', padding: '80px 20px 140px', position: 'relative', zIndex: 1 }}>
        <ScrollReveal>
          <div className="section-label">Applications</div>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em' }}>
            {loading ? 'LOADING...' : apps.length > 0 ? `${apps.length} APPLICATIONS` : 'APPLICATIONS'}
          </h1>
        </ScrollReveal>

        {/* Filter chips — only show when there are apps */}
        {apps.length > 0 && (
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

        <ScrollReveal delay={2}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, overflow: 'hidden' }}>
            {loading ? (
              <div style={{ padding: 60, textAlign: 'center', color: 'var(--t3)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>Loading...</div>
            ) : filtered.length > 0 ? (
              filtered.map((app, i) => {
                const cfg = STATUS_CONFIG[app.status] || { color: 'var(--t3)', label: app.status };
                const activeStep = app.status === 'submitted' ? 0 : -1;
                return (
                  <div key={app.id || i} style={{
                    display: 'grid', gridTemplateColumns: '3px 1fr auto', gap: '0 16px',
                    padding: '16px 20px 16px 0', borderBottom: '1px solid var(--b)', transition: 'background 0.15s',
                  }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(139,92,246,0.02)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = '')}
                  >
                    <div style={{ width: 3, borderRadius: 2, alignSelf: 'stretch', background: cfg.color }} />
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {app.job.company} — {app.job.title}
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 4, display: 'flex', gap: 12 }}>
                        <span>{app.created_at ? new Date(app.created_at).toLocaleDateString() : ''}</span>
                        <span style={{ textTransform: 'capitalize' }}>{app.trigger}</span>
                        {app.screenshot_url && (
                          <span style={{ color: 'var(--g)', display: 'flex', alignItems: 'center', gap: 4 }}>
                            <span style={{ fontSize: 10 }}>✓</span> Receipt
                          </span>
                        )}
                      </div>
                      {/* Screenshot receipt */}
                      {app.screenshot_url && (
                        <div style={{
                          marginTop: 10, borderRadius: 8, overflow: 'hidden',
                          border: '1px solid var(--b)', background: 'var(--bg)',
                        }}>
                          <a href={app.screenshot_url} target="_blank" rel="noopener noreferrer">
                            <img
                              src={app.screenshot_url}
                              alt={`Application receipt for ${app.job.company}`}
                              style={{ width: '100%', maxHeight: 200, objectFit: 'cover', display: 'block' }}
                            />
                          </a>
                          <div style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--g)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                            Submission confirmed · {app.submitted_at ? new Date(app.submitted_at).toLocaleString() : ''}
                          </div>
                        </div>
                      )}
                      {/* Lifecycle */}
                      <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginTop: 8 }}>
                        {LIFECYCLE.map((step, si) => (
                          <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <div style={{
                              width: 7, height: 7, borderRadius: '50%',
                              background: si <= activeStep ? 'var(--g)' : 'var(--b)',
                              border: si <= activeStep ? 'none' : '1px solid rgba(255,255,255,0.1)',
                              boxShadow: si === activeStep ? '0 0 6px var(--g)' : 'none',
                            }} />
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: si <= activeStep ? 'var(--g)' : 'var(--t3)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                              {step}
                            </span>
                            {si < LIFECYCLE.length - 1 && <div style={{ width: 12, height: 1, background: si < activeStep ? 'var(--g)' : 'var(--b)' }} />}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div style={{ alignSelf: 'center' }}>
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, padding: '3px 10px', borderRadius: 4,
                        background: `${cfg.color}15`, color: cfg.color, textTransform: 'uppercase', letterSpacing: '0.04em',
                      }}>
                        {cfg.label}
                      </span>
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
                  <Link href="/jobs" className="btn-violet">Browse Jobs →</Link>
                )}
              </div>
            )}
          </div>
        </ScrollReveal>
      </main>
    </AuthGuard>
  );
}
