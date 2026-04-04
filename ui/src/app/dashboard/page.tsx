'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import PageSkeleton from '@/components/PageSkeleton';
import SummaryBar from '@/components/briefing/SummaryBar';
import MorningBriefing from '@/components/briefing/MorningBriefing';
import ActivityFeed from '@/components/feed/ActivityFeed';
import { useAgent } from '@/components/agent/AgentProvider';
import QuestionReviewPanel from '@/components/QuestionReviewPanel';
import { getDashboard, getActivityFeed, getMorningBriefing, getDashboardStats, getMatches, uploadResume, listApplications } from '@/lib/api';

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
  const router = useRouter();
  const { send, open } = useAgent();
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

  // Top matches
  const [topMatches, setTopMatches] = useState<Array<{ match_id: string; match_score: number; job: { id: string; title: string; company: string; location: string; ats_type: string; apply_url: string } }>>([]);

  // Discovered jobs (from TinyFish discovery)
  const [discoveredJobs, setDiscoveredJobs] = useState<Array<{ title?: string; company?: string; location?: string; apply_url?: string; description?: string; salary?: string }>>([]);
  const [discoveryQuery, setDiscoveryQuery] = useState('');

  // Question review panel
  const [reviewAppId, setReviewAppId] = useState<string | null>(null);
  const [pendingAppIds, setPendingAppIds] = useState<string[]>([]);

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
      getMatches({ min_score: 55, per_page: 5 }).catch(() => null),
      listApplications({ status: 'waiting_user_input', per_page: 10 }).catch(() => null),
    ]).then(([dashResult, statsResult, briefingResult, feedResult, matchesResult, pendingAppsResult]) => {
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
        const allEvents = f.events || [];
        setEvents(allEvents);
        setFeedHasMore(f.has_more || false);
        // Extract most recent discovery results
        const discoveryEvent = allEvents.find((e: any) => e.type === 'discovery_completed' && e.metadata?.jobs?.length);
        if (discoveryEvent) {
          setDiscoveredJobs(discoveryEvent.metadata.jobs);
          setDiscoveryQuery(discoveryEvent.metadata.query || '');
        }
      }
      if (matchesResult.status === 'fulfilled' && matchesResult.value) {
        const m = matchesResult.value as any;
        setTopMatches((m.items || []).slice(0, 5));
      }
      if (pendingAppsResult.status === 'fulfilled' && pendingAppsResult.value) {
        const pa = pendingAppsResult.value as any;
        setPendingAppIds((pa.items || []).map((a: any) => a.id));
      }
    }).finally(() => setLoading(false));
  }, []);

  // Poll for updates every 30 seconds (activity feed + stats + matches)
  useEffect(() => {
    if (loading || noProfile) return;
    const interval = setInterval(async () => {
      try {
        const [feedData, statsData, matchData] = await Promise.all([
          getActivityFeed(1, 20).catch(() => null),
          getDashboardStats().catch(() => null),
          getMatches({ min_score: 55, per_page: 5 }).catch(() => null),
        ]);
        if (feedData) {
          const allEvents = feedData.events || [];
          setEvents(allEvents);
          setFeedHasMore(feedData.has_more || false);
          const discoveryEvent = allEvents.find((e: any) => e.type === 'discovery_completed' && e.metadata?.jobs?.length);
          if (discoveryEvent) {
            setDiscoveredJobs((discoveryEvent as any).metadata?.jobs || []);
            setDiscoveryQuery(String((discoveryEvent as any).metadata?.query || ''));
          }
        }
        if (statsData) {
          setStats({
            totalMatches: statsData.total_matches || 0,
            totalApplications: statsData.total_applications || 0,
            autopilotEnabled: statsData.autopilot_enabled || false,
            autopilotThreshold: statsData.autopilot_threshold || 70,
            applicationsThisMonth: statsData.applications_this_month || 0,
            monthlyLimit: statsData.monthly_limit || 0,
          });
        }
        if (matchData) {
          setTopMatches(((matchData as any).items || []).slice(0, 5));
        }
      } catch { /* silent */ }
    }, 30000);
    return () => clearInterval(interval);
  }, [loading, noProfile]);

  // Redirect to onboarding if no profile exists
  useEffect(() => {
    if (!loading && noProfile) {
      router.replace('/onboard');
    }
  }, [loading, noProfile, router]);

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

        {noProfile ? (
          null  /* useEffect below handles redirect to /onboard */
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

            {/* Pending questions alert — above everything */}
            {pendingAppIds.length > 0 && (
              <div style={{
                background: 'var(--sf)',
                border: '1px solid rgba(251,191,36,0.18)',
                borderRadius: 12,
                padding: '14px 20px',
                marginTop: 16,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 16,
              }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>Foxhound needs your input</div>
                  <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>
                    {pendingAppIds.length} application{pendingAppIds.length !== 1 ? 's have' : ' has'} questions before Foxhound can finish.
                  </div>
                </div>
                <button
                  onClick={() => setReviewAppId(pendingAppIds[0] || null)}
                  style={{
                    fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warning)',
                    textTransform: 'uppercase', letterSpacing: '0.05em',
                    border: '1px solid rgba(251,191,36,0.18)', borderRadius: 6,
                    padding: '8px 12px', flexShrink: 0, whiteSpace: 'nowrap',
                    background: 'none', cursor: 'pointer',
                  }}
                >
                  Review Questions
                </button>
              </div>
            )}

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
                      {stats.totalApplications > 0
                        ? 'Your search is moving.'
                        : topMatches.length > 0
                          ? `${topMatches.filter(m => m.match_score >= 70).length} strong matches ready.`
                          : 'Searching for matches.'}
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
                      animation: topMatches.length === 0 && stats.totalApplications === 0 ? 'pulse 2s infinite' : 'none',
                    }} />
                    {stats.autopilotEnabled ? 'Autonomy On' : 'Review Mode'}
                  </span>
                </div>
                <p style={{ fontSize: 14, color: 'var(--t2)', lineHeight: 1.7, marginTop: 12, marginBottom: 0 }}>
                  {stats.totalApplications > 0
                    ? `Foxhound applied to ${stats.totalApplications} role${stats.totalApplications !== 1 ? 's' : ''} and is monitoring each one. New matches are checked daily.`
                    : topMatches.length > 0
                      ? (stats.autopilotEnabled
                          ? `Foxhound will start applying to your strongest matches automatically. You can also pick one from below and apply now.`
                          : `Review your top matches below. Pick one to apply, or turn on autonomy in settings to let Foxhound handle it.`)
                      : resumeFilename
                        ? 'Foxhound is scanning job boards and the web for roles that fit your profile. First matches usually appear within a few hours.'
                        : 'Foxhound is looking for jobs. Add a resume so it can start applying for you.'}
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
                  <QueueRow label="Strong Fits" value={`${topMatches.length > 0 ? topMatches.filter(m => m.match_score >= 70).length : stats.totalMatches} above 70%`} tone="var(--vl)" />
                  <QueueRow label="Applications" value={`${stats.totalApplications} submitted`} tone="var(--g)" />
                  <QueueRow label="Questions" value={pendingQuestions > 0 ? `${pendingQuestions} waiting on you` : 'All clear'} tone={pendingQuestions > 0 ? 'var(--warning)' : 'var(--t3)'} />
                </div>
              </div>
            </div>

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

            {/* Morning Briefing */}
            {briefing && (
              <MorningBriefing
                generatedAt={briefing.generated_at}
                summary={briefing.summary}
                applications={briefing.applications}
                alerts={briefing.alerts}
                newMatches={briefing.new_matches}
                onApply={(jobId) => {
                  const match = briefing.new_matches?.find((m: any) => m.job_id === jobId);
                  if (match) {
                    open();
                    setTimeout(() => send(`Apply to ${match.company} ${match.title}`), 300);
                  }
                }}
              />
            )}

            {/* Pending questions alert moved above status section */}

            {/* Top Matches */}
            {topMatches.length > 0 && (
              <div style={{
                background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                padding: 20, marginTop: 24,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                  <div>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)',
                      textTransform: 'uppercase', letterSpacing: '0.08em',
                    }}>
                      Top Matches
                    </span>
                    <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>
                      Your strongest fits right now
                    </div>
                  </div>
                  <Link href="/jobs" style={{
                    fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                    textTransform: 'uppercase', letterSpacing: '0.06em',
                  }}>
                    View all &rarr;
                  </Link>
                </div>
                {topMatches.map((m) => (
                  <div key={m.match_id} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 0', borderBottom: '1px solid var(--b)',
                  }}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {m.job.company} — {m.job.title}
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 3 }}>
                        {m.job.location || 'Remote'}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, marginLeft: 12 }}>
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700,
                        color: m.match_score >= 80 ? 'var(--g)' : m.match_score >= 70 ? 'var(--vl)' : 'var(--t3)',
                      }}>
                        {m.match_score}%
                      </span>
                      <button
                        onClick={() => {
                          open();
                          setTimeout(() => send(`Apply to ${m.job.company} ${m.job.title}`), 300);
                        }}
                        style={{
                          fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
                          textTransform: 'uppercase', letterSpacing: '0.04em',
                          padding: '4px 10px', borderRadius: 4,
                          border: '1px solid var(--bv)', background: 'transparent',
                          cursor: 'pointer', whiteSpace: 'nowrap',
                        }}
                      >
                        Apply
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Jobs Discovered */}
            {discoveredJobs.length > 0 && (
              <div style={{
                background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                padding: 20, marginTop: 24,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                  <div>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)',
                      textTransform: 'uppercase', letterSpacing: '0.08em',
                    }}>
                      Jobs Discovered
                    </span>
                    <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>
                      {discoveryQuery ? `Results for "${discoveryQuery}"` : 'Found by Foxhound'}
                    </div>
                  </div>
                  <Link href="/intelligence" style={{
                    fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                    textTransform: 'uppercase', letterSpacing: '0.06em',
                  }}>
                    New search &rarr;
                  </Link>
                </div>
                {discoveredJobs.map((job, i) => (
                  <div key={i} style={{
                    padding: '12px 0',
                    borderBottom: i < discoveredJobs.length - 1 ? '1px solid var(--b)' : 'none',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: 14, fontWeight: 500, lineHeight: 1.3 }}>
                          {job.title || 'Untitled Position'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3, flexWrap: 'wrap' }}>
                          {job.company && (
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)' }}>
                              {job.company}
                            </span>
                          )}
                          {job.company && job.location && (
                            <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--t3)' }} />
                          )}
                          {job.location && (
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)' }}>
                              {job.location}
                            </span>
                          )}
                          {job.salary && (
                            <>
                              <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--t3)' }} />
                              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)' }}>
                                {job.salary}
                              </span>
                            </>
                          )}
                        </div>
                        {job.description && (
                          <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 6, lineHeight: 1.5, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const }}>
                            {job.description}
                          </div>
                        )}
                      </div>
                      {job.apply_url && (
                        <a
                          href={job.apply_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
                            textTransform: 'uppercase', letterSpacing: '0.04em',
                            padding: '4px 10px', borderRadius: 4,
                            border: '1px solid var(--bv)', background: 'transparent',
                            whiteSpace: 'nowrap', flexShrink: 0,
                          }}
                        >
                          View
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

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
                onAnswerQuestions={(appId) => setReviewAppId(appId)}
              />
            </div>
          </>
        )}
      </main>

      {/* Question review modal */}
      {reviewAppId && (
        <QuestionReviewPanel
          applicationId={reviewAppId}
          allAppIds={pendingAppIds}
          isOpen={true}
          onClose={() => setReviewAppId(null)}
          onSubmitted={() => {
            setReviewAppId(null);
            // Refresh pending apps
            listApplications({ status: 'waiting_user_input', per_page: 50 })
              .then((pa: any) => setPendingAppIds((pa.items || []).map((a: any) => a.id)))
              .catch(() => {});
          }}
        />
      )}
    </AuthGuard>
  );
}
