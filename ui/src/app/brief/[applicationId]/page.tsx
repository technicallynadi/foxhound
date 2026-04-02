'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import PageSkeleton from '@/components/PageSkeleton';
import { getBrief } from '@/lib/api';

interface BriefSubmission {
  pre_submit_screenshot?: string | null;
  ats_type?: string | null;
  method?: string | null;
  fields_filled?: string[] | null;
}

interface BriefPostingStatus {
  watchdog_status?: string | null;
  ghost_score?: number | null;
  ghost_risk?: string | null;
}

interface BriefData {
  company?: string;
  title?: string;
  match_score?: number | null;
  applied_at?: string | null;
  generated_at?: string | null;
  submission?: BriefSubmission | null;
  posting_status?: BriefPostingStatus | null;
  company_brief?: {
    summary?: string | null;
    tech_stack?: string[] | null;
    hiring_velocity?: string | null;
    insider_tip?: string | null;
  } | null;
  pathfinder?: {
    manager_signals?: {
      likely_title?: string | null;
      department?: string | null;
    } | null;
    search_urls?: {
      linkedin?: string | null;
    } | null;
    overlap?: {
      summary_for_outreach?: string | null;
    } | null;
    outreach?: {
      linkedin_note?: string | null;
      email_body?: string | null;
      email_subject?: string | null;
    } | null;
  } | null;
  recommended_next_action?: {
    label?: string | null;
    detail?: string | null;
    href?: string | null;
    href_label?: string | null;
    priority?: 'low' | 'normal' | 'high' | null;
  } | null;
}

const mono = { fontFamily: 'var(--font-mono)' };
const display = { fontFamily: 'var(--font-display)' };

export default function BriefPage() {
  const params = useParams();
  const applicationId = params.applicationId as string;
  const [brief, setBrief] = useState<BriefData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!applicationId) return;
    getBrief(applicationId)
      .then((data) => setBrief(data as BriefData))
      .catch((e) => setError(e.message || 'Failed to load brief'))
      .finally(() => setLoading(false));
  }, [applicationId]);

  if (loading) return <AuthGuard><AppNav /><PageSkeleton variant="dashboard" /></AuthGuard>;

  if (error || !brief) {
    return (
      <AuthGuard>
        <AppNav />
        <main style={{ maxWidth: 900, margin: '0 auto', padding: '80px 20px 140px' }}>
          <div style={{ textAlign: 'center', padding: '64px 0', color: 'var(--t3)' }}>
            <div style={{ ...display, fontSize: 20, fontWeight: 700, marginBottom: 8, color: 'var(--t)' }}>Brief not available</div>
            <p style={{ fontSize: 14, maxWidth: 520, margin: '0 auto' }}>
              {error || 'No brief found for this application.'} Foxhound may still be assembling the research cascade for this role.
            </p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 10, flexWrap: 'wrap', marginTop: 18 }}>
              <Link href={`/intelligence?tab=brief&applicationId=${applicationId}`} style={{ ...mono, fontSize: 11, color: 'var(--vl)', textTransform: 'uppercase', display: 'inline-block' }}>
                Open Research
              </Link>
              <Link href="/applications" style={{ ...mono, fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', display: 'inline-block' }}>
                Back to Applications
              </Link>
            </div>
          </div>
        </main>
      </AuthGuard>
    );
  }

  const pathfinder = brief.pathfinder || {};
  const companyBrief = brief.company_brief || {};
  const managerSignals = pathfinder.manager_signals || {};
  const outreach = pathfinder.outreach || {};
  const searchUrls = pathfinder.search_urls || {};
  const fieldsFilled = brief.submission?.fields_filled ?? [];
  const techStack = companyBrief.tech_stack ?? [];

  return (
    <AuthGuard>
      <AppNav />
      <main style={{ maxWidth: 900, margin: '0 auto', padding: '80px 20px 140px' }}>

        {/* Header */}
        <div style={{ marginBottom: 32 }}>
          <Link href="/dashboard" style={{ ...mono, fontSize: 10, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12, display: 'inline-block' }}>
            &larr; Dashboard
          </Link>
          <div style={{ ...mono, fontSize: 11, color: 'var(--vl)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>
            FOXHOUND BRIEF
          </div>
          <h1 style={{ ...display, fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 4 }}>
            {brief.company} — {brief.title}
          </h1>
          <div style={{ ...mono, fontSize: 11, color: 'var(--t3)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {brief.match_score && <span>{brief.match_score}% match</span>}
            {brief.match_score && <span>&middot;</span>}
            {brief.applied_at && <span>Applied {new Date(brief.applied_at).toLocaleDateString()}</span>}
            {brief.generated_at && (
              <>
                <span>&middot;</span>
                <span>Brief generated {new Date(brief.generated_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>
              </>
            )}
          </div>
        </div>

        {/* Top row: Submission + Posting Status */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          {/* Submission */}
          <Card>
            <CardLabel>SUBMISSION</CardLabel>
            {brief.submission?.pre_submit_screenshot && (
              <div style={{ marginBottom: 12, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--b)' }}>
                <div style={{ position: 'relative', width: '100%', height: 200 }}>
                  <Image
                    src={brief.submission.pre_submit_screenshot}
                    alt="Application screenshot"
                    fill
                    unoptimized
                    sizes="(max-width: 900px) 100vw, 900px"
                    style={{ objectFit: 'cover' }}
                  />
                </div>
              </div>
            )}
            <div style={{ fontSize: 13, color: 'var(--t2)' }}>
              Submitted via {brief.submission?.ats_type || 'the company site'}
            </div>
            <div style={{ ...mono, fontSize: 11, color: 'var(--t3)', marginTop: 4 }}>
              {brief.submission?.method === 'api' ? 'Submitted directly' : 'Submitted through the application form'}
            </div>
            {fieldsFilled.length > 0 && (
              <div style={{ ...mono, fontSize: 11, color: 'var(--t3)', marginTop: 4 }}>
                {fieldsFilled.length} questions answered
              </div>
            )}
          </Card>

          {/* Posting Status */}
          <Card>
            <CardLabel>POSTING STATUS</CardLabel>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: brief.posting_status?.watchdog_status === 'active' ? 'var(--g)' : 'var(--warning)',
              }} />
              <span style={{ fontSize: 14, fontWeight: 500 }}>
                {brief.posting_status?.watchdog_status === 'active' ? 'Active' : 'Unknown'}
              </span>
            </div>
            {brief.posting_status?.ghost_score != null && (
              <div style={{ ...mono, fontSize: 11, color: brief.posting_status.ghost_score >= 60 ? 'var(--warning)' : 'var(--t3)', marginTop: 4 }}>
                Ghost risk: {brief.posting_status.ghost_score}/100
                {brief.posting_status.ghost_risk && ` (${brief.posting_status.ghost_risk})`}
              </div>
            )}
            <div style={{ ...mono, fontSize: 11, color: 'var(--t3)', marginTop: 4 }}>
              Foxhound is watching this posting
            </div>
          </Card>
        </div>

        {/* Company Context */}
        {companyBrief.summary && (
          <Card style={{ marginBottom: 16 }}>
            <CardLabel>ABOUT THE COMPANY</CardLabel>
            <div style={{ ...display, fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
              {brief.company}
            </div>
            {techStack.length > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                {techStack.map((tech: string) => (
                  <span key={tech} style={{
                    ...mono, fontSize: 11, color: 'var(--vl)',
                    background: 'var(--vf)', border: '1px solid var(--bv)',
                    borderRadius: 4, padding: '2px 8px',
                  }}>
                    {tech}
                  </span>
                ))}
              </div>
            )}
            <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6 }}>
              {companyBrief.summary}
            </div>
            {companyBrief.hiring_velocity && (
              <div style={{ ...mono, fontSize: 12, color: 'var(--t3)', marginTop: 12 }}>
                Hiring pace: {companyBrief.hiring_velocity}
              </div>
            )}
            {companyBrief.insider_tip && (
              <div style={{
                fontSize: 13, color: 'var(--t2)', marginTop: 12,
                padding: '8px 12px', background: 'var(--vf)',
                borderLeft: '2px solid var(--v)', borderRadius: '0 6px 6px 0',
              }}>
                {companyBrief.insider_tip}
              </div>
            )}
          </Card>
        )}

        {/* Best Contact */}
        {managerSignals.likely_title && (
          <Card style={{ marginBottom: 16 }}>
            <CardLabel>BEST CONTACT</CardLabel>
            <div style={{ ...display, fontSize: 16, fontWeight: 600 }}>
              {managerSignals.likely_title}
            </div>
            <div style={{ fontSize: 13, color: 'var(--t2)', marginTop: 2 }}>
              {managerSignals.department || 'Unknown department'}
            </div>
            {searchUrls.linkedin && (
              <a href={searchUrls.linkedin} target="_blank" rel="noopener noreferrer" style={{
                ...mono, fontSize: 12, color: 'var(--vl)', marginTop: 8, display: 'inline-block',
              }}>
                Search on LinkedIn &rarr;
              </a>
            )}
            {pathfinder.overlap?.summary_for_outreach && (
              <div style={{
                fontSize: 13, color: 'var(--t)', marginTop: 12,
                padding: '8px 12px', background: 'var(--vf)',
                borderLeft: '2px solid var(--v)', borderRadius: '0 6px 6px 0',
              }}>
                Why they might respond: {pathfinder.overlap.summary_for_outreach}
              </div>
            )}
          </Card>
        )}

        {/* Outreach Drafts */}
        {(outreach.linkedin_note || outreach.email_body) && (
          <Card style={{ marginBottom: 16 }}>
            <CardLabel>READY-TO-SEND MESSAGES</CardLabel>

            {outreach.linkedin_note && (
              <DraftBlock
                label={`LINKEDIN NOTE (${outreach.linkedin_note.length} chars)`}
                text={outreach.linkedin_note}
              />
            )}

            {outreach.email_body && (
              <DraftBlock
                label={outreach.email_subject ? `EMAIL — ${outreach.email_subject}` : 'EMAIL DRAFT'}
                text={outreach.email_body}
              />
            )}
          </Card>
        )}

        {/* Recommended Next Steps */}
        {brief.recommended_next_action?.detail && (
          <Card>
            <CardLabel>WHAT TO DO NEXT</CardLabel>
            {brief.recommended_next_action.label && (
              <div style={{ ...display, fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
                {brief.recommended_next_action.label}
              </div>
            )}
            <div style={{ fontSize: 14, color: 'var(--t2)', lineHeight: 1.6 }}>
              {brief.recommended_next_action.detail}
            </div>
            {brief.recommended_next_action.href && (
              <Link
                href={brief.recommended_next_action.href}
                style={{
                  ...mono,
                  fontSize: 10,
                  color: 'var(--vl)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  marginTop: 10,
                  display: 'inline-block',
                }}
              >
                {brief.recommended_next_action.href_label || 'Open Next Step'}
              </Link>
            )}
          </Card>
        )}
      </main>
    </AuthGuard>
  );
}

/* ─── Sub-components ─── */

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
      padding: 20, ...style,
    }}>
      {children}
    </div>
  );
}

function CardLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)',
      textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 12,
    }}>
      {children}
    </div>
  );
}

function DraftBlock({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6,
      }}>
        {label}
      </div>
      <div style={{
        background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8,
        padding: 14, fontSize: 13, color: 'var(--t2)', lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
      }}>
        {text}
      </div>
      <button onClick={copy} style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase',
        letterSpacing: '0.04em', marginTop: 6,
        color: copied ? 'var(--g)' : 'var(--t3)',
        background: 'none', border: 'none', cursor: 'pointer',
      }}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}
