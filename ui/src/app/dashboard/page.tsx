'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import ScrollReveal from '@/components/landing/ScrollReveal';
import { getDashboard, getMatches, uploadResume } from '@/lib/api';

interface DashboardData {
  profile: { name: string; tier: string; applications_this_month: number; monthly_limit: number; autopilot_enabled: boolean; profile_complete: boolean; resume_filename: string | null };
  applications: { total: number; by_status: Record<string, number>; recent: Array<{ application_id: string; company: string; title: string; status: string; created_at: string; submitted_at?: string }> };
  matches: { total: number; top_score: number | null };
  pending_questions: number;
}

const STATUS_COLORS: Record<string, string> = {
  submitted: 'var(--g)', scanning: 'var(--vl)', in_progress: 'var(--vl)',
  waiting_user_input: 'var(--warning)', failed: 'var(--error)', needs_manual: 'var(--warning)',
};

interface MatchItem {
  match_id: string;
  match_score: number;
  job: { id: string; title: string; company: string; location: string; remote_type: string | null; ats_type: string; apply_url: string };
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [matches, setMatches] = useState<MatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [noProfile, setNoProfile] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');

  /* eslint-disable react-hooks/set-state-in-effect -- async API calls set state in .then() */
  useEffect(() => {
    Promise.allSettled([
      getDashboard(),
      getMatches({ per_page: 10 }),
    ]).then(([dashResult, matchResult]) => {
      if (dashResult.status === 'fulfilled') {
        const result = dashResult.value as Record<string, unknown>;
        if (result.error === 'no_profile') {
          setNoProfile(true);
        } else {
          setData(dashResult.value as unknown as DashboardData);
        }
      }
      if (matchResult.status === 'fulfilled') {
        setMatches((matchResult.value as { items: MatchItem[] }).items || []);
      }
    }).finally(() => setLoading(false));
  }, []); /* eslint-enable react-hooks/set-state-in-effect */

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  };

  return (
    <AuthGuard>
      <AppNav />
      <main style={{ paddingTop: 80, maxWidth: 1100, margin: '0 auto', padding: '80px 20px 140px', position: 'relative', zIndex: 1 }}>

        {/* Header */}
        <ScrollReveal>
          <div className="section-label">Dashboard</div>
          <h1 style={{
            fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700,
            letterSpacing: '-0.02em', marginBottom: 4,
          }}>
            {greeting()}{data?.profile?.name ? `, ${data.profile.name.split(' ')[0]}` : ''}
          </h1>
          <p style={{ fontSize: 14, color: 'var(--t2)' }}>
            {loading ? 'Loading...' : data ? `${data.matches?.total || 0} job matches · ${data.applications?.total || 0} applications` : 'Upload your resume to get started'}
          </p>
        </ScrollReveal>

        {/* No profile — onboarding CTA */}
        {!loading && (noProfile || (!data && !loading)) && (
          <ScrollReveal delay={1}>
            <div style={{
              background: 'var(--sf)', border: '1px solid var(--bv)', borderRadius: 12,
              padding: '48px 32px', marginTop: 32, textAlign: 'center',
            }}>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 8 }}>
                Let&apos;s get started
              </div>
              <p style={{ fontSize: 14, color: 'var(--t2)', marginBottom: 24, maxWidth: 400, margin: '0 auto 24px' }}>
                Upload your resume and Foxhound will start finding jobs that match your skills and experience.
              </p>
              <Link href="/onboard" className="btn-solid">Upload Resume →</Link>
            </div>
          </ScrollReveal>
        )}

        {/* Dashboard content — only when we have data */}
        {data && (
          <>
            {/* Stats */}
            <ScrollReveal delay={1}>
              <div className="dashboard-stats" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, marginTop: 32, background: 'var(--b)', border: '1px solid var(--b)' }}>
                {[
                  { label: 'Applications', value: data.applications?.total || 0, sub: `${data.profile?.applications_this_month || 0}/${data.profile?.monthly_limit || '\u221E'} this month` },
                  { label: 'Submitted', value: data.applications?.by_status?.submitted || 0, sub: '' },
                  { label: 'Matches', value: data.matches?.total || 0, sub: data.matches?.top_score ? `Top: ${data.matches.top_score}%` : '' },
                  { label: 'Pending', value: data.pending_questions || 0, sub: 'questions' },
                ].map((s) => (
                  <div key={s.label} style={{ background: 'var(--bg)', padding: 24 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
                      {s.label}
                    </div>
                    <div style={{ fontFamily: 'var(--font-display)', fontSize: 32, fontWeight: 700, letterSpacing: '-0.02em' }}>
                      {s.value}
                    </div>
                    {s.sub && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 4 }}>{s.sub}</div>}
                  </div>
                ))}
              </div>
            </ScrollReveal>

            {/* Resume upload */}
            <ScrollReveal delay={2}>
              <div style={{
                background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                padding: '16px 24px', marginTop: 16,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              }}>
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                    Resume
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>
                    {data.profile.resume_filename || 'No resume uploaded'}
                    {uploadMsg && <span style={{ color: uploadMsg.includes('Updated') ? 'var(--g)' : 'var(--error)', marginLeft: 8 }}>{uploadMsg}</span>}
                  </div>
                </div>
                <label style={{
                  fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
                  letterSpacing: '0.04em', textTransform: 'uppercase',
                  padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
                  border: '1px solid var(--b)', background: 'transparent',
                  transition: 'all 0.2s',
                }}>
                  <input type="file" accept=".pdf" style={{ display: 'none' }} onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    setUploading(true);
                    setUploadMsg('');
                    try {
                      await uploadResume(file);
                      setUploadMsg('Updated — rescoring matches');
                      window.location.reload();
                    } catch {
                      setUploadMsg('Upload failed');
                    }
                    setUploading(false);
                  }} />
                  {uploading ? 'Uploading...' : 'Update Resume'}
                </label>
              </div>
            </ScrollReveal>

            {/* Recent Applications */}
            <ScrollReveal delay={2}>
              <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: 24, marginTop: 32 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                    Recent Applications
                  </div>
                  <Link href="/applications" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                    View all →
                  </Link>
                </div>

                {data.applications?.recent?.length ? (
                  data.applications.recent.map((app) => (
                    <div key={app.application_id} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '12px 0', borderBottom: '1px solid var(--b)',
                    }}>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 400 }}>
                          {app.company} — {app.title}
                        </div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 3 }}>
                          {new Date(app.created_at).toLocaleDateString()}
                        </div>
                      </div>
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
                        padding: '3px 10px', borderRadius: 4,
                        background: `${STATUS_COLORS[app.status] || 'var(--t3)'}15`,
                        color: STATUS_COLORS[app.status] || 'var(--t3)',
                        textTransform: 'uppercase', letterSpacing: '0.04em',
                      }}>
                        {app.status.replace(/_/g, ' ')}
                      </span>
                    </div>
                  ))
                ) : (
                  <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--t3)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                    No applications yet. Browse <Link href="/jobs" style={{ color: 'var(--vl)' }}>open roles</Link> to get started.
                  </div>
                )}
              </div>
            </ScrollReveal>

            {/* Top Matches */}
            {matches.length > 0 && (
              <ScrollReveal delay={3}>
                <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: 24, marginTop: 16 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 16 }}>
                    Top Matches
                  </div>
                  {matches.map((m) => (
                    <div key={m.match_id} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '12px 0', borderBottom: '1px solid var(--b)',
                    }}>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: 14, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {m.job.company} — {m.job.title}
                        </div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 3 }}>
                          {m.job.location || 'Remote'} · {m.job.ats_type}
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0, marginLeft: 16 }}>
                        <span style={{
                          fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 700,
                          color: m.match_score >= 80 ? 'var(--g)' : m.match_score >= 60 ? 'var(--vl)' : 'var(--t3)',
                        }}>
                          {m.match_score}%
                        </span>
                        {m.job.apply_url && (
                          <a href={m.job.apply_url} target="_blank" rel="noopener noreferrer" style={{
                            fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                            textTransform: 'uppercase', letterSpacing: '0.04em',
                          }}>
                            Apply →
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollReveal>
            )}

            {/* Tier info */}
            <ScrollReveal delay={3}>
              <div style={{
                marginTop: 16, padding: '16px 20px', background: 'var(--sf)',
                border: '1px solid var(--b)', borderRadius: 8,
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                  Plan: {data.profile.tier} · Autopilot: {data.profile.autopilot_enabled ? 'On' : 'Off'}
                </div>
                <Link href="/settings" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                  Settings →
                </Link>
              </div>
            </ScrollReveal>
          </>
        )}
      </main>
    </AuthGuard>
  );
}
