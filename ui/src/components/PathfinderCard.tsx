'use client';

import { useState, useCallback } from 'react';
import { getAccessToken } from '@/lib/supabase';

export interface PathfinderManagerSignals {
  department?: string | null;
  likely_title?: string | null;
  team_size_hint?: string | null;
  seniority_of_manager?: string | null;
  reporting_clues?: string | null;
  confidence?: 'high' | 'medium' | 'low' | string | null;
}

export interface PathfinderOverlap {
  shared_skills?: string[] | null;
  user_only_skills?: string[] | null;
  job_only_skills?: string[] | null;
  industry_match?: boolean | null;
  industry_details?: string | null;
  location_match?: boolean | null;
  location_details?: string | null;
  seniority_alignment?: 'match' | 'stretch' | 'overqualified' | 'unknown' | string | null;
  overlap_score?: number | null;
  summary_for_outreach?: string | null;
}

export interface PathfinderOutreach {
  linkedin_note?: string | null;
  email_subject?: string | null;
  email_body?: string | null;
  personalization_hooks?: string[] | null;
}

export interface PathfinderConfirmedManager {
  name?: string | null;
  title?: string | null;
  team?: string | null;
  source?: string | null;
  source_url?: string | null;
}

export interface PathfinderData {
  manager_signals?: PathfinderManagerSignals | null;
  search_urls?: { linkedin?: string | null; google?: string | null } | null;
  overlap?: PathfinderOverlap | null;
  outreach?: PathfinderOutreach | null;
  confirmed_manager?: PathfinderConfirmedManager | null;
  company?: string | null;
  job_title?: string | null;
  job_id?: string | null;
}

interface PathfinderCardProps {
  jobId: string | null;
  initialData?: PathfinderData | null;
  companyName: string;
  jobTitle?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

async function fetchPathfinder(jobId: string): Promise<PathfinderData> {
  const token = await getAccessToken();
  const res = await fetch(`${API_BASE}/api/v1/pathfinder/${jobId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    let msg = `Pathfinder error ${res.status}`;
    try { msg = JSON.parse(body).detail || msg; } catch { }
    throw new Error(msg);
  }
  return res.json();
}

function Divider() {
  return (
    <div
      aria-hidden="true"
      style={{
        height: 1,
        background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.12), transparent)',
        margin: '18px 0',
      }}
    />
  );
}

function SectionLabel({ index, children }: { index: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600, color: 'var(--vl)', letterSpacing: '0.08em', opacity: 0.6 }}>
        {index.padStart(2, '0')}
      </span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500, color: 'var(--vl)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
        {children}
      </span>
    </div>
  );
}

function ConfidenceBadge({ level }: { level: string }) {
  const map: Record<string, { bg: string; color: string; border: string }> = {
    high: { bg: 'rgba(52,211,153,0.08)', color: 'var(--g)', border: 'rgba(52,211,153,0.2)' },
    medium: { bg: 'rgba(139,92,246,0.08)', color: 'var(--vl)', border: 'var(--bv)' },
    low: { bg: 'rgba(240,240,240,0.04)', color: 'var(--t3)', border: 'var(--b)' },
  };
  const s = map[level.toLowerCase()] || map.low;
  return (
    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', padding: '2px 7px', borderRadius: 3, background: s.bg, color: s.color, border: `1px solid ${s.border}` }}>
      {level}
    </span>
  );
}

function OverlapBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const barColor = pct >= 70 ? 'var(--g)' : 'linear-gradient(90deg, var(--v), var(--vl))';
  const textColor = pct >= 70 ? 'var(--g)' : pct >= 40 ? 'var(--vl)' : 'var(--t3)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, height: 3, borderRadius: 2, background: 'var(--b)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, borderRadius: 2, background: barColor, transition: 'width 0.8s ease-out' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: textColor, letterSpacing: '-0.02em', minWidth: 36, textAlign: 'right' }}>
        {pct}
      </span>
    </div>
  );
}

function SkillBadge({ name, variant }: { name: string; variant: 'shared' | 'gap' }) {
  const styles = {
    shared: { bg: 'rgba(52,211,153,0.07)', color: 'var(--g)', border: 'rgba(52,211,153,0.18)' },
    gap: { bg: 'rgba(248,113,113,0.07)', color: 'rgba(248,113,113,0.9)', border: 'rgba(248,113,113,0.18)' },
  };
  const s = styles[variant];
  return (
    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500, padding: '3px 8px', borderRadius: 4, background: s.bg, color: s.color, border: `1px solid ${s.border}`, letterSpacing: '0.01em' }}>
      {name}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { }
  }, [text]);
  return (
    <button
      onClick={handleCopy}
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
      style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase',
        padding: '4px 10px', borderRadius: 4, cursor: 'pointer',
        border: `1px solid ${copied ? 'rgba(52,211,153,0.3)' : 'var(--b)'}`,
        background: copied ? 'rgba(52,211,153,0.08)' : 'transparent',
        color: copied ? 'var(--g)' : 'var(--t3)',
        transition: 'all 0.2s', minHeight: 28, flexShrink: 0,
      }}
      onMouseEnter={(e) => { if (!copied) { e.currentTarget.style.borderColor = 'var(--bv)'; e.currentTarget.style.color = 'var(--vl)'; } }}
      onMouseLeave={(e) => { if (!copied) { e.currentTarget.style.borderColor = 'var(--b)'; e.currentTarget.style.color = 'var(--t3)'; } }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function SearchLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href} target="_blank" rel="noopener noreferrer"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
        color: 'var(--vl)', textDecoration: 'none',
        padding: '5px 12px', border: '1px solid var(--bv)', borderRadius: 5,
        background: 'var(--vf)', transition: 'all 0.2s', minHeight: 30, whiteSpace: 'nowrap',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(139,92,246,0.12)'; e.currentTarget.style.borderColor = 'var(--v)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--vf)'; e.currentTarget.style.borderColor = 'var(--bv)'; }}
    >
      {label} <span aria-hidden="true" style={{ fontSize: 9 }}>↗</span>
    </a>
  );
}

function ShimmerBlock({ w, h }: { w?: string | number; h: number }) {
  return (
    <div
      className="pfc-skel"
      style={{ width: w ?? '100%', height: h, borderRadius: 4, background: 'var(--el)', position: 'relative', overflow: 'hidden' }}
    />
  );
}

function LoadingState() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '2px 0' }}>
      <ShimmerBlock h={11} w="70%" />
      <ShimmerBlock h={11} w="50%" />
      <div style={{ height: 4 }} />
      <ShimmerBlock h={11} w="85%" />
      <ShimmerBlock h={11} w="60%" />
    </div>
  );
}

export default function PathfinderCard({ jobId, initialData, companyName, jobTitle }: PathfinderCardProps) {
  const [data, setData] = useState<PathfinderData | null>(initialData ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runAnalysis = useCallback(async () => {
    if (!jobId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchPathfinder(jobId);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  const manager = data?.manager_signals;
  const confirmed = data?.confirmed_manager;
  const overlap = data?.overlap;
  const outreach = data?.outreach;
  const searchUrls = data?.search_urls;
  const hasManagerData = !!(manager?.likely_title || confirmed?.name);
  const hasOverlap = !!(overlap?.overlap_score != null || (overlap?.shared_skills && overlap.shared_skills.length > 0));
  const hasOutreach = !!(outreach?.linkedin_note || outreach?.email_body);
  const outreachSectionIndex = (hasManagerData ? 1 : 0) + (hasOverlap ? 1 : 0) + 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>

      {!data && !loading && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 12, padding: '4px 0' }}>
          <p style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--t3)', lineHeight: 1.6, margin: 0 }}>
            Identify the hiring manager at {companyName}{jobTitle ? ` for the ${jobTitle} role` : ''}, analyze your profile fit, and generate personalized outreach.
          </p>
          {jobId ? (
            <button
              onClick={runAnalysis}
              style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', padding: '8px 18px', borderRadius: 6, cursor: 'pointer', border: '1px solid var(--bv)', background: 'var(--vf)', color: 'var(--vl)', transition: 'all 0.2s', minHeight: 36 }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(139,92,246,0.12)'; e.currentTarget.style.borderColor = 'var(--v)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--vf)'; e.currentTarget.style.borderColor = 'var(--bv)'; }}
            >
              Run Pathfinder Analysis
            </button>
          ) : (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.04em' }}>
              Job ID unavailable — run from the job detail page.
            </span>
          )}
          {error && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(248,113,113,0.9)' }}>{error}</span>}
        </div>
      )}

      {loading && (
        <div style={{ paddingTop: 8 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="pfc-pulse" style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--v)', display: 'inline-block' }} />
            Analyzing
          </div>
          <LoadingState /><Divider /><LoadingState /><Divider /><LoadingState />
        </div>
      )}

      {data && !loading && (
        <div style={{ paddingTop: 4 }}>

          {!hasManagerData && !hasOverlap && !hasOutreach && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '8px 0' }}>
              <p style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--t3)', lineHeight: 1.6, margin: 0 }}>
                Pathfinder found limited data for this company and role. Try searching LinkedIn directly.
              </p>
              {searchUrls?.linkedin && (
                <div style={{ display: 'flex', gap: 8 }}>
                  <SearchLink href={searchUrls.linkedin} label="Search LinkedIn" />
                </div>
              )}
            </div>
          )}

          {hasManagerData && (
            <>
              <SectionLabel index="1">Hiring Manager</SectionLabel>
              {confirmed?.name ? (
                <div style={{ background: 'rgba(52,211,153,0.04)', border: '1px solid rgba(52,211,153,0.15)', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--g)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Confirmed</span>
                  </div>
                  <div style={{ fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 700, color: 'var(--t)', letterSpacing: '-0.01em' }}>{confirmed.name}</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 3, letterSpacing: '0.02em' }}>
                    {confirmed.title}{confirmed.team ? ` · ${confirmed.team}` : ''}
                  </div>
                  {(confirmed.source || confirmed.source_url) && (
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)', marginTop: 6, letterSpacing: '0.04em', opacity: 0.8 }}>
                      via{' '}
                      {confirmed.source_url ? (
                        <a href={confirmed.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--vl)', textDecoration: 'none' }}>
                          {confirmed.source || confirmed.source_url} ↗
                        </a>
                      ) : confirmed.source}
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ background: 'var(--vf)', border: '1px solid var(--bv)', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600, color: 'var(--t)', letterSpacing: '-0.01em' }}>{manager?.likely_title || 'Unknown Title'}</div>
                      {manager?.department && (
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 2, letterSpacing: '0.02em' }}>
                          {manager.department}{manager.team_size_hint && manager.team_size_hint !== 'unknown' ? ` · ${manager.team_size_hint}` : ''}
                        </div>
                      )}
                    </div>
                    {manager?.confidence && <ConfidenceBadge level={manager.confidence} />}
                  </div>
                  {manager?.reporting_clues && (
                    <div style={{ fontFamily: 'var(--font-body)', fontSize: 12, color: 'var(--t3)', lineHeight: 1.55, borderLeft: '2px solid var(--bv)', paddingLeft: 10, marginTop: 8, fontStyle: 'italic' }}>
                      {manager.reporting_clues}
                    </div>
                  )}
                </div>
              )}
              {(searchUrls?.linkedin || searchUrls?.google) && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {searchUrls.linkedin && <SearchLink href={searchUrls.linkedin} label="Search LinkedIn" />}
                  {searchUrls.google && <SearchLink href={searchUrls.google} label="Google Search" />}
                </div>
              )}
            </>
          )}

          {hasOverlap && (
            <>
              {hasManagerData && <Divider />}
              <SectionLabel index={hasManagerData ? '2' : '1'}>Profile Fit</SectionLabel>
              {overlap?.overlap_score != null && (
                <div style={{ marginBottom: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8, gap: 8 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Overlap Score</span>
                    {overlap.seniority_alignment && overlap.seniority_alignment !== 'unknown' && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: overlap.seniority_alignment === 'match' ? 'var(--g)' : 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                        {overlap.seniority_alignment}
                      </span>
                    )}
                  </div>
                  <OverlapBar score={overlap.overlap_score} />
                </div>
              )}
              {overlap?.summary_for_outreach && (
                <div style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--t2)', lineHeight: 1.6, borderLeft: '3px solid var(--v)', paddingLeft: 12, marginBottom: 12 }}>
                  {overlap.summary_for_outreach}
                </div>
              )}
              {overlap?.shared_skills && overlap.shared_skills.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>Shared Skills</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                    {overlap.shared_skills.slice(0, 10).map((s) => <SkillBadge key={s} name={s} variant="shared" />)}
                  </div>
                </div>
              )}
              {overlap?.job_only_skills && overlap.job_only_skills.length > 0 && (
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>Skills to Address</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                    {overlap.job_only_skills.slice(0, 8).map((s) => <SkillBadge key={s} name={s} variant="gap" />)}
                  </div>
                </div>
              )}
            </>
          )}

          {hasOutreach && (
            <>
              {(hasManagerData || hasOverlap) && <Divider />}
              <SectionLabel index={String(outreachSectionIndex)}>Outreach Drafts</SectionLabel>
              <div style={{ display: 'inline-flex', alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', padding: '4px 10px', borderRadius: 100, background: 'rgba(139,92,246,0.08)', color: 'var(--vl)', border: '1px solid var(--bv)', marginBottom: 14 }}>
                AI DRAFT — review and edit before sending
              </div>
              {outreach?.personalization_hooks && outreach.personalization_hooks.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>Personalization Hooks</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {outreach.personalization_hooks.map((hook, i) => (
                      <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 12, fontFamily: 'var(--font-body)', color: 'var(--t3)', lineHeight: 1.55 }}>
                        <span style={{ color: 'var(--v)', fontSize: 7, flexShrink: 0, marginTop: 5 }}>●</span>
                        {hook}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {outreach?.linkedin_note && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                      LinkedIn Note <span style={{ opacity: 0.6, marginLeft: 6 }}>({outreach.linkedin_note.length} chars)</span>
                    </div>
                    <CopyButton text={outreach.linkedin_note} />
                  </div>
                  <div style={{ background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 6, padding: 12, fontSize: 13, fontFamily: 'var(--font-body)', color: 'var(--t2)', lineHeight: 1.65, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {outreach.linkedin_note}
                  </div>
                </div>
              )}
              {outreach?.email_body && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                      {outreach.email_subject ? `Email — ${outreach.email_subject}` : 'Email Draft'}
                    </div>
                    <CopyButton text={outreach.email_body} />
                  </div>
                  <div style={{ background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 6, padding: 12, fontSize: 13, fontFamily: 'var(--font-body)', color: 'var(--t2)', lineHeight: 1.65, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {outreach.email_body}
                  </div>
                </div>
              )}
            </>
          )}

          {jobId && (
            <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--b)' }}>
              <button
                onClick={runAnalysis}
                style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 500, letterSpacing: '0.06em', textTransform: 'uppercase', padding: '4px 10px', borderRadius: 4, cursor: 'pointer', border: '1px solid var(--b)', background: 'transparent', color: 'var(--t2)', transition: 'all 0.2s', minHeight: 26 }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--bv)'; e.currentTarget.style.color = 'var(--vl)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--b)'; e.currentTarget.style.color = 'var(--t2)'; }}
              >
                Re-run Analysis
              </button>
            </div>
          )}
        </div>
      )}

      {error && data && (
        <div style={{ marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(248,113,113,0.9)' }}>{error}</div>
      )}

      <style>{`
        .pfc-skel::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.04) 40%, rgba(255,255,255,0.06) 50%, rgba(255,255,255,0.04) 60%, transparent 100%);
          animation: pfc-shimmer 1.8s ease-in-out infinite;
        }
        @keyframes pfc-shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
        @keyframes pfc-pulse-anim { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        .pfc-pulse { animation: pfc-pulse-anim 1.5s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) { .pfc-skel::after { animation: none; } .pfc-pulse { animation: none; } }
      `}</style>
    </div>
  );
}
