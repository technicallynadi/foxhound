'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import PageSkeleton from '@/components/PageSkeleton';
import SummaryBar from '@/components/briefing/SummaryBar';
import MorningBriefing from '@/components/briefing/MorningBriefing';
import ActivityFeed from '@/components/feed/ActivityFeed';
import { getDashboard, getActivityFeed, getMorningBriefing, getDashboardStats, uploadResume } from '@/lib/api';

/* eslint-disable @typescript-eslint/no-explicit-any */

function streamColor(autopilotEnabled: boolean) {
  return autopilotEnabled ? 'var(--g)' : 'var(--warning)';
}

function QueueRow({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </span>
      <span style={{ fontSize: 13, color: tone }}>{value}</span>
    </div>
  );
}

export default function DashboardPage() {
  const [profileName, setProfileName] = useState('');
  const [noProfile, setNoProfile] = useState(false);
  const [loading, setLoading] = useState(true);

  // Stats
  const [stats, setStats] = useState({
    totalMatches: 0,
    totalApplications: 0,
    autopilotEnabled: false,
    autopilotThreshold: 70,
    applicationsThisMonth: 0,
    monthlyLimit: 0,
  });

  // Morning briefing
  const [briefing, setBriefing] = useState<any>(null);

  // Activity feed
  const [events, setEvents] = useState<any[]>([]);
  const [feedPage, setFeedPage] = useState(1);
  const [feedHasMore, setFeedHasMore] = useState(false);
  const [feedLoading, setFeedLoading] = useState(false);

  // Resume
  const [resumeFilename, setResumeFilename] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');

  const pendingQuestions = briefing?.summary?.questions_pending || 0;
  const hasAgentActivity = events.length > 0 || (briefing && (briefing.summary?.applications_submitted || briefing.summary?.matches_above_threshold || briefing.summary?.alerts_count));

  useEffect(() => {
    Promise.allSettled([
      getDashboard(),
      getDashboardStats().catch(() => null),
      getMorningBriefing().catch(() => null),
      getActivityFeed(1, 20).catch(() => null),
    ]).then(([dashResult, statsResult, briefingResult, feedResult]) => {
      if (dashResult.status === 'fulfilled') {
        const d = dashResult.value as any;
        if (d.error === 'no_profile') {
          setNoProfile(true);
        } else {
          setProfileName(d.profile?.name?.split(' ')[0] || '');
          setResumeFilename(d.profile?.resume_filename || null);
          // Fallback stats from dashboard if stats endpoint not available
          setStats({
            totalMatches: d.matches?.total || 0,
            totalApplications: d.applications?.total || 0,
            autopilotEnabled: d.profile?.autopilot_enabled || false,
            autopilotThreshold: 70,
            applicationsThisMonth: d.profile?.applications_this_month || 0,
            monthlyLimit: d.profile?.monthly_limit || 0,
          });
        }
      }
      if (statsResult.status === 'fulfilled' && statsResult.value) {
        const s = statsResult.value as any;
        setStats({
          totalMatches: s.total_matches || 0,
          totalApplications: s.total_applications || 0,
          autopilotEnabled: s.autopilot_enabled || false,
          autopilotThreshold: s.autopilot_threshold || 70,
          applicationsThisMonth: s.applications_this_month || 0,
          monthlyLimit: s.monthly_limit || 0,
        });
      }
      if (briefingResult.status === 'fulfilled' && briefingResult.value) {
        setBriefing(briefingResult.value);
      }
      if (feedResult.status === 'fulfilled' && feedResult.value) {
        const f = feedResult.value as any;
        setEvents(f.events || []);
        setFeedHasMore(f.has_more || false);
      }
    }).finally(() => setLoading(false));
  }, []);

  const loadMoreEvents = useCallback(async () => {
    if (feedLoading) return;
    setFeedLoading(true);
    try {
      const next = feedPage + 1;
      const result = await getActivityFeed(next, 20);
      setEvents((prev) => [...prev, ...result.events]);
      setFeedPage(next);
      setFeedHasMore(result.has_more);
    } catch { /* ignore */ }
    setFeedLoading(false);
  }, [feedPage, feedLoading]);

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  };

  if (loading) {
    return (
      <AuthGuard>
        <AppNav />
        <PageSkeleton variant="dashboard" />
      </AuthGuard>
    );
  }

  return (
    <AuthGuard>
      <AppNav />
      <main style={{ maxWidth: 1100, margin: '0 auto', padding: '80px 20px 140px', position: 'relative', zIndex: 1 }}>

        {/* No profile — onboarding CTA */}
        {noProfile ? (
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
            <Link href="/onboard" className="btn-solid">Upload Resume &rarr;</Link>
          </div>
        ) : (
          <>
            {/* Greeting + Summary Bar */}
            <div>
              <h1 style={{
                fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700,
                letterSpacing: '-0.02em', marginBottom: 4,
              }}>
                {greeting()}{profileName ? `, ${profileName}` : ''}
              </h1>
              <SummaryBar
                totalMatches={stats.totalMatches}
                totalApplications={stats.totalApplications}
                autopilotEnabled={stats.autopilotEnabled}
                autopilotThreshold={stats.autopilotThreshold}
                applicationsThisMonth={stats.applicationsThisMonth}
                monthlyLimit={stats.monthlyLimit}
              />
            </div>

            <div style={{
              marginTop: 24,
              display: 'grid',
              gridTemplateColumns: '1.2fr 0.8fr',
              gap: 16,
            }}>
              <div style={{
                background: 'var(--sf)',
                border: '1px solid var(--bv)',
                borderRadius: 12,
                padding: 20,
              }}>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                }}>
                  <div>
                    <div style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10,
                      color: 'var(--vl)',
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                    }}>
                      Foxhound Status
                    </div>
                    <div style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: 20,
                      fontWeight: 700,
                      letterSpacing: '-0.02em',
                      marginTop: 6,
                    }}>
                      {hasAgentActivity ? 'Your search is already moving.' : 'Foxhound is watching your pipeline.'}
                    </div>
                  </div>
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    color: streamColor(stats.autopilotEnabled),
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}>
                    <span style={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      background: streamColor(stats.autopilotEnabled),
                      display: 'inline-block',
                    }} />
                    {stats.autopilotEnabled ? 'Autonomy On' : 'Review Mode'}
                  </span>
                </div>
                <p style={{ fontSize: 14, color: 'var(--t2)', lineHeight: 1.7, marginTop: 12, marginBottom: 0 }}>
                  {resumeFilename
                    ? 'Foxhound finds jobs, checks if postings are still live, researches people and companies, and keeps tracking every application after you hit apply.'
                    : 'Foxhound is already finding jobs for you. Add a resume when you want it to start applying for you.'}
                </p>
              </div>

              <div style={{
                background: 'var(--sf)',
                border: '1px solid var(--b)',
                borderRadius: 12,
                padding: 20,
              }}>
                <div style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--t3)',
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  marginBottom: 10,
                }}>
                  At a Glance
                </div>
                <div style={{ display: 'grid', gap: 10 }}>
                  <QueueRow label="Matches" value={`${stats.totalMatches} jobs found`} tone="var(--vl)" />
                  <QueueRow label="Applications" value={`${stats.totalApplications} submitted`} tone="var(--g)" />
                  <QueueRow label="Questions" value={pendingQuestions > 0 ? `${pendingQuestions} waiting on you` : 'All clear'} tone={pendingQuestions > 0 ? 'var(--warning)' : 'var(--t3)'} />
                </div>
              </div>
            </div>

            {/* Morning Briefing */}
            {briefing && (
              <MorningBriefing
                generatedAt={briefing.generated_at}
                summary={briefing.summary}
                applications={briefing.applications}
                alerts={briefing.alerts}
                newMatches={briefing.new_matches}
              />
            )}

            {pendingQuestions > 0 && (
              <div style={{
                background: 'var(--sf)',
                border: '1px solid rgba(251,191,36,0.18)',
                borderRadius: 12,
                padding: '16px 20px',
                marginTop: 16,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 16,
              }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>Foxhound is waiting on your input</div>
                  <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>
                    Some applications need your input before Foxhound can finish them.
                  </div>
                </div>
                <Link href="/applications" style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--warning)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  border: '1px solid rgba(251,191,36,0.18)',
                  borderRadius: 6,
                  padding: '8px 12px',
                  flexShrink: 0,
                }}>
                  Review Questions
                </Link>
              </div>
            )}

            {/* Resume bar */}
            <div style={{
              background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
              padding: '12px 20px', marginTop: 16,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Resume
                </span>
                <span style={{ fontSize: 13, color: 'var(--t3)' }}>
                  {resumeFilename || 'No resume uploaded'}
                  {uploadMsg && <span style={{ color: uploadMsg.includes('Updated') ? 'var(--g)' : 'var(--error)', marginLeft: 8 }}>{uploadMsg}</span>}
                </span>
              </div>
              <label style={{
                fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
                letterSpacing: '0.04em', textTransform: 'uppercase',
                padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
                border: '1px solid var(--b)', background: 'transparent',
              }}>
                <input type="file" accept=".pdf" style={{ display: 'none' }} onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setUploading(true);
                  setUploadMsg('');
                  try {
                    await uploadResume(file);
                    setUploadMsg('Updated');
                    setResumeFilename(file.name);
                  } catch {
                    setUploadMsg('Upload failed');
                  }
                  setUploading(false);
                }} />
                {uploading ? 'Uploading...' : 'Update'}
              </label>
            </div>

            {/* Activity Feed */}
            <div style={{ marginTop: 32 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)',
                    textTransform: 'uppercase', letterSpacing: '0.08em',
                  }}>
                    Activity
                  </span>
                  <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>
                    Everything Foxhound did, in order.
                  </div>
                </div>
              </div>
              <ActivityFeed
                events={events}
                loading={feedLoading}
                hasMore={feedHasMore}
                onLoadMore={loadMoreEvents}
              />
            </div>
          </>
        )}
      </main>
    </AuthGuard>
  );
}
