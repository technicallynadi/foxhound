'use client';

import { useState, useCallback, type ReactNode } from 'react';
import Link from 'next/link';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || '';

function storageUrl(path: string): string {
  return `${SUPABASE_URL}/storage/v1/object/public/${path}`;
}

interface Props {
  toolName: string;
  data: Record<string, unknown>;
  onSend?: (message: string) => void;
}

type ActionPriority = 'low' | 'normal' | 'high';

interface ProcessContext {
  applicationId: string;
  company?: string;
  role?: string;
  status?: string;
  postingStatus?: string;
  daysSinceApplied?: number;
  followupDay3Sent?: boolean;
  followupDay7Sent?: boolean;
  followupDay14Sent?: boolean;
}

interface NextAction {
  label: string;
  detail: string;
  href?: string;
  hrefLabel?: string;
  priority?: ActionPriority;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

function extractContext(data: Record<string, unknown>): ProcessContext | null {
  const raw = asRecord(data.application_context) || data;
  const applicationId = typeof raw.application_id === 'string'
    ? raw.application_id
    : typeof data.application_id === 'string'
      ? data.application_id
      : '';
  if (!applicationId) return null;

  return {
    applicationId,
    company: typeof raw.company === 'string' ? raw.company : undefined,
    role:
      typeof raw.role === 'string'
        ? raw.role
        : typeof raw.title === 'string'
          ? raw.title
          : typeof data.job_title === 'string'
            ? data.job_title
            : undefined,
    status:
      typeof raw.status === 'string'
        ? raw.status
        : typeof data.status === 'string'
          ? data.status
          : undefined,
    postingStatus:
      typeof raw.posting_status === 'string'
        ? raw.posting_status
        : typeof data.posting_status === 'string'
          ? data.posting_status
          : undefined,
    daysSinceApplied: typeof raw.days_since_applied === 'number' ? raw.days_since_applied : undefined,
    followupDay3Sent: Boolean(raw.followup_day3_sent),
    followupDay7Sent: Boolean(raw.followup_day7_sent),
    followupDay14Sent: Boolean(raw.followup_day14_sent),
  };
}

function deriveActionFromContext(context: ProcessContext): NextAction {
  const status = context.status || '';
  const posting = context.postingStatus || 'unknown';
  const days = context.daysSinceApplied || 0;

  if (status === 'waiting_user_input') {
    return {
      label: 'Answer pending questions now',
      detail: 'Foxhound is blocked waiting for your input before it can finish this application.',
      href: '/applications',
      hrefLabel: 'Open Applications',
      priority: 'high',
    };
  }

  if (posting === 'removed') {
    return {
      label: 'Archive this role and redirect effort',
      detail: 'The posting appears removed, so follow-up energy should move to stronger live opportunities.',
      href: '/applications',
      hrefLabel: 'Manage Application',
      priority: 'high',
    };
  }

  if (days >= 14 && !context.followupDay14Sent) {
    return {
      label: 'Send final day-14 follow-up',
      detail: 'This is the final high-leverage follow-up window before deprioritizing if there is no response.',
      href: `/brief/${context.applicationId}`,
      hrefLabel: 'Open Brief',
      priority: 'high',
    };
  }

  if (days >= 7 && !context.followupDay7Sent) {
    return {
      label: 'Send day-7 follow-up now',
      detail: 'Use your strongest company + people signal in a concise follow-up message.',
      href: `/brief/${context.applicationId}`,
      hrefLabel: 'Open Brief',
      priority: 'high',
    };
  }

  if (days >= 3 && !context.followupDay3Sent) {
    return {
      label: 'Prepare your day-3 follow-up',
      detail: 'Have your first follow-up ready so Foxhound can send at the right timing window.',
      href: `/brief/${context.applicationId}`,
      hrefLabel: 'Open Brief',
      priority: 'normal',
    };
  }

  if (posting === 'edited') {
    return {
      label: 'Review posting changes before outreach',
      detail: 'The role changed after you applied. Recalibrate your follow-up narrative with the updated posting.',
      href: `/brief/${context.applicationId}`,
      hrefLabel: 'Open Brief',
      priority: 'normal',
    };
  }

  return {
    label: 'Let Foxhound keep monitoring this application',
    detail: 'Research and status checks are active. Act when Foxhound surfaces a meaningful change.',
    href: `/brief/${context.applicationId}`,
    hrefLabel: 'Open Brief',
    priority: 'low',
  };
}

function extractAction(
  data: Record<string, unknown>,
  context: ProcessContext | null,
): NextAction | null {
  const raw = data.recommended_next_action;
  if (typeof raw === 'string' && raw.trim()) {
    return {
      label: 'Recommended next action',
      detail: raw.trim(),
      priority: 'normal',
    };
  }
  const rec = asRecord(raw);
  if (rec && typeof rec.label === 'string' && typeof rec.detail === 'string') {
    return {
      label: rec.label,
      detail: rec.detail,
      href: typeof rec.href === 'string' ? rec.href : undefined,
      hrefLabel: typeof rec.href_label === 'string' ? rec.href_label : undefined,
      priority:
        rec.priority === 'low' || rec.priority === 'high' || rec.priority === 'normal'
          ? rec.priority
          : 'normal',
    };
  }
  return context ? deriveActionFromContext(context) : null;
}

function seededIntelligenceHref(
  tab: 'people' | 'brief' | 'interview' | 'status' | 'discovery',
  opts: { company?: string; role?: string; applicationId?: string },
): string {
  const params = new URLSearchParams({ tab });
  if (opts.company) params.set('company', opts.company);
  if (opts.role) params.set('role', opts.role);
  if (opts.applicationId) params.set('applicationId', opts.applicationId);
  return `/intelligence?${params.toString()}`;
}

function briefHref(applicationId?: string, briefReady?: unknown): string | null {
  if (!applicationId || !briefReady) return null;
  return `/brief/${applicationId}`;
}

function ActionRow({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
      {children}
    </div>
  );
}

function ActionLink({ href, label, emphasis = false }: { href: string; label: string; emphasis?: boolean }) {
  return (
    <Link
      href={href}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        padding: '6px 10px',
        borderRadius: 6,
        border: `1px solid ${emphasis ? 'var(--bv)' : 'var(--b)'}`,
        color: emphasis ? 'var(--vl)' : 'var(--t3)',
        background: emphasis ? 'rgba(139,92,246,0.08)' : 'transparent',
        display: 'inline-flex',
        alignItems: 'center',
        textDecoration: 'none',
      }}
    >
      {label}
    </Link>
  );
}

function ProcessContextCard({
  context,
  action,
}: {
  context: ProcessContext | null;
  action: NextAction | null;
}) {
  if (!context && !action) return null;

  const posting = context?.postingStatus || 'unknown';
  const postingColor =
    posting === 'active'
      ? 'var(--g)'
      : posting === 'edited'
        ? 'var(--warning)'
        : posting === 'removed'
          ? 'var(--error)'
          : 'var(--t3)';
  const days = context?.daysSinceApplied;

  return (
    <div
      style={{
        marginTop: 10,
        padding: 10,
        borderRadius: 8,
        border: '1px solid var(--b)',
        background: 'rgba(255,255,255,0.02)',
      }}
    >
      {context && (
        <>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--t3)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              marginBottom: 6,
            }}
          >
            Application Process Context
          </div>
          <div style={{ fontSize: 11, color: 'var(--t2)', lineHeight: 1.6 }}>
            {context.status && (
              <div>
                <span style={{ color: 'var(--t3)' }}>Status:</span>{' '}
                {context.status.replace(/_/g, ' ')}
              </div>
            )}
            <div>
              <span style={{ color: 'var(--t3)' }}>Posting:</span>{' '}
              <span style={{ color: postingColor }}>{posting}</span>
            </div>
            {typeof days === 'number' && (
              <div>
                <span style={{ color: 'var(--t3)' }}>Applied:</span>{' '}
                {days} day{days === 1 ? '' : 's'} ago
              </div>
            )}
          </div>
        </>
      )}
      {action && (
        <div style={{ marginTop: context ? 8 : 0 }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color:
                action.priority === 'high'
                  ? 'var(--warning)'
                  : action.priority === 'low'
                    ? 'var(--t3)'
                    : 'var(--vl)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              marginBottom: 4,
            }}
          >
            Recommended Next Action
          </div>
          <div style={{ fontSize: 12, color: 'var(--t)', fontWeight: 600 }}>
            {action.label}
          </div>
          <div style={{ fontSize: 11, color: 'var(--t2)', lineHeight: 1.6, marginTop: 2 }}>
            {action.detail}
          </div>
          {action.href && (
            <Link
              href={action.href}
              style={{
                display: 'inline-block',
                marginTop: 6,
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--vl)',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              {action.hrefLabel || 'Open'} &rarr;
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

export default function ToolResultCard({ toolName, data, onSend }: Props) {
  if (toolName === 'search_jobs' || toolName === 'get_matches' || toolName === 'discover_jobs') {
    const items = (data.jobs || data.matches || []) as Array<Record<string, unknown>>;
    if (items.length === 0) return null;
    const first = items[0];
    const firstRole = first?.title as string | undefined;

    return (
      <div style={{ padding: '3px 0' }}>
        <div style={{ background: 'var(--el)', border: '1px solid var(--b)', padding: 10, borderRadius: 12 }}>
          {items.slice(0, 5).map((item, i) => (
            <div key={item.job_id as string || i} style={{
              padding: '7px 0',
              borderBottom: i < Math.min(items.length, 5) - 1 ? '1px solid var(--b)' : 'none',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{item.title as string}</div>
                <div style={{ color: 'var(--t3)', fontSize: 12 }}>
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
              fontSize: 12, color: 'var(--vl)',
            }}>
              View all {items.length} results
            </Link>
          )}
          <ActionRow>
            <ActionLink href="/jobs" label="Open Jobs" emphasis />
            {firstRole && (
              <ActionLink
                href={seededIntelligenceHref('discovery', { role: firstRole })}
                label="Open Discovery"
              />
            )}
          </ActionRow>
        </div>
      </div>
    );
  }

  if (toolName === 'apply_to_job' || toolName === 'check_application_status') {
    const errorCode = data.error as string | undefined;
    const status = data.status as string;
    const company = data.company as string;
    const title = (data.job_title || data.title || '') as string;
    const applicationId = data.application_id as string | undefined;
    const questions = (data.pending_questions || []) as Array<Record<string, unknown>>;
    const preScreenshot = data.pre_submit_screenshot as string | undefined;
    const postScreenshot = data.screenshot as string | undefined;
    const hasScreenshots = !!(preScreenshot || postScreenshot);
    const briefLink = briefHref(applicationId, data.brief_ready);
    const context = extractContext({
      ...data,
      company,
      role: title,
      application_id: applicationId,
      status,
    });
    const nextAction = extractAction(data, context);

    if (errorCode === 'resume_required') {
      return (
        <div style={{ padding: '3px 0' }}>
          <div style={{
            background: 'var(--el)', border: '1px solid var(--b)', padding: 12, borderRadius: 12,
            borderLeft: '3px solid var(--warning)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>Resume required before Foxhound can apply</div>
            <div style={{ color: 'var(--t2)', fontSize: 12, marginTop: 6, lineHeight: 1.6 }}>
              {(data.message as string) || 'Foxhound can keep hunting now, but it needs your resume before it can submit applications.'}
            </div>
            <ActionRow>
              <ActionLink href="/onboard" label="Add Resume" emphasis />
              <ActionLink href="/jobs" label="Keep Hunting" />
            </ActionRow>
          </div>
        </div>
      );
    }

    // Below threshold — show coaching with gap analysis
    if (errorCode === 'below_quality_floor') {
      const matchScore = data.match_score as number;
      const gap = data.gap_analysis as Record<string, unknown> | undefined;
      const alternatives = (data.alternatives || []) as Array<Record<string, unknown>>;

      return (
        <div style={{ padding: '3px 0' }}>
          <div style={{
            background: 'var(--el)', border: '1px solid var(--b)', padding: 12, borderRadius: 12,
            borderLeft: '3px solid var(--warning)',
          }}>
            {/* Score badge */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>Below quality floor</div>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700,
                color: 'var(--warning)',
              }}>
                {matchScore}%
              </span>
            </div>

            {/* Gap analysis */}
            {gap && (
              <div style={{ marginBottom: 10 }}>
                {/* Missing required skills */}
                {Array.isArray(gap.missing_required) && (gap.missing_required as string[]).length > 0 && (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--error)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
                      Missing required
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {(gap.missing_required as string[]).slice(0, 6).map((s) => (
                        <span key={s} style={{
                          fontFamily: 'var(--font-mono)', fontSize: 10,
                          padding: '2px 6px', borderRadius: 3,
                          background: 'rgba(248,113,113,0.1)', color: 'var(--error)',
                          border: '1px solid rgba(248,113,113,0.15)',
                        }}>
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Matching skills */}
                {Array.isArray(gap.matching_skills) && (gap.matching_skills as string[]).length > 0 && (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--g)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
                      You match on
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {(gap.matching_skills as string[]).slice(0, 6).map((s) => (
                        <span key={s} style={{
                          fontFamily: 'var(--font-mono)', fontSize: 10,
                          padding: '2px 6px', borderRadius: 3,
                          background: 'rgba(52,211,153,0.1)', color: 'var(--g)',
                          border: '1px solid rgba(52,211,153,0.15)',
                        }}>
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Coaching summary */}
                {!!(gap.summary) && (
                  <div style={{
                    fontSize: 12, color: 'var(--t2)', lineHeight: 1.5, marginTop: 8,
                    padding: '8px 10px', background: 'var(--bg)', borderRadius: 6,
                    borderLeft: '2px solid var(--warning)',
                  }}>
                    {gap.summary as string}
                  </div>
                )}
              </div>
            )}

            {/* Alternatives */}
            {alternatives.length > 0 && (
              <div style={{ borderTop: '1px solid var(--b)', paddingTop: 8, marginTop: 4 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--vl)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
                  Stronger matches
                </div>
                {alternatives.map((alt, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '4px 0',
                  }}>
                    <span style={{ fontSize: 12 }}>
                      {alt.company as string} — {alt.title as string}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700,
                      color: 'var(--g)',
                    }}>
                      {alt.match_score as number}%
                    </span>
                  </div>
                ))}
              </div>
            )}
            <ActionRow>
              <ActionLink href="/jobs" label="Open Jobs" emphasis />
              {company && (
                <ActionLink
                  href={seededIntelligenceHref('discovery', { company, role: title })}
                  label="Find Better Fits"
                />
              )}
              <ActionLink href="/profile" label="Improve Profile" />
            </ActionRow>
          </div>
        </div>
      );
    }

    return (
      <div style={{ padding: '3px 0' }}>
        <div style={{
          background: 'var(--el)', border: '1px solid var(--b)', padding: 10, borderRadius: 12,
          borderLeft: `3px solid ${statusColor(status)}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{company}{title ? ` — ${title}` : ''}</div>
              <div style={{ color: 'var(--t3)', fontSize: 12, marginTop: 1 }}>{statusLabel(status)}</div>
            </div>
            <StatusBadge status={status} />
          </div>
          {hasScreenshots && (
            <ScreenshotRow
              preScreenshot={preScreenshot}
              postScreenshot={postScreenshot}
            />
          )}
          {questions.length > 0 && (
            <QuestionForm questions={questions} onSend={onSend} />
          )}
          <ProcessContextCard context={context} action={nextAction} />
          <ActionRow>
            <ActionLink href="/applications" label="Open Tracker" emphasis />
            {briefLink && <ActionLink href={briefLink} label="Open Brief" />}
            {company && (
              <ActionLink
                href={seededIntelligenceHref('people', { company, role: title, applicationId })}
                label="People Research"
              />
            )}
            {company && (
              <ActionLink
                href={seededIntelligenceHref('status', { company, role: title, applicationId })}
                label="Status Tracker"
              />
            )}
          </ActionRow>
        </div>
      </div>
    );
  }

  if (toolName === 'answer_application_questions') {
    const status = data.status as string;
    const remaining = (data.remaining_questions || []) as Array<Record<string, unknown>>;

    if (status === 'all_answered') {
      return (
        <div style={{ padding: '3px 0' }}>
          <div style={{
            background: 'var(--el)', border: '1px solid var(--b)', padding: 10, borderRadius: 12,
            borderLeft: '3px solid var(--g)',
          }}>
            <div style={{ fontSize: 13, color: 'var(--g)', fontWeight: 500 }}>
              All questions answered — submitting application
            </div>
            <div style={{ fontSize: 11, color: 'var(--t3)', marginTop: 4 }}>
              You can close this chat. I&apos;ll notify you when it&apos;s done.
            </div>
            <ActionRow>
              <ActionLink href="/applications" label="Open Tracker" emphasis />
            </ActionRow>
          </div>
        </div>
      );
    }

    if (remaining.length > 0) {
      return (
        <div style={{ padding: '3px 0' }}>
          <div style={{ background: 'var(--el)', border: '1px solid var(--b)', padding: 10, borderRadius: 12 }}>
            <QuestionForm questions={remaining} onSend={onSend} />
          </div>
        </div>
      );
    }

    return null;
  }

  if (toolName === 'get_applications') {
    const apps = (data.applications || []) as Array<Record<string, unknown>>;
    if (apps.length === 0) return null;
    const top = apps[0];
    const topContext = extractContext(top);
    const topAction = extractAction(top, topContext);
    return (
      <div style={{ padding: '3px 0' }}>
        <div style={{ background: 'var(--el)', border: '1px solid var(--b)', padding: 10, borderRadius: 12 }}>
          {apps.slice(0, 5).map((app, i) => (
            <div key={app.application_id as string || i} style={{
              padding: '5px 0',
              borderBottom: i < Math.min(apps.length, 5) - 1 ? '1px solid var(--b)' : 'none',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12,
            }}>
              <div>
                <div>{app.company as string} — {app.title as string}</div>
                {typeof app.application_id === 'string' && app.application_id && (
                  <Link href={`/brief/${app.application_id}`} style={{ fontSize: 11, color: 'var(--vl)' }}>
                    Open brief
                  </Link>
                )}
              </div>
              <StatusBadge status={app.status as string} />
            </div>
          ))}
          <ProcessContextCard context={topContext} action={topAction} />
          <ActionRow>
            <ActionLink href="/applications" label="Open Tracker" emphasis />
          </ActionRow>
        </div>
      </div>
    );
  }

  if (toolName === 'get_dossier') {
    const status = data.status as string | undefined;
    const dossierId = data.dossier_id as string | undefined;
    const applicationId = data.application_id as string | undefined;
    const context = extractContext({
      ...data,
      application_id: applicationId,
    });
    const nextAction = extractAction(data, context);
    return (
      <div style={{ padding: '3px 0' }}>
        <div style={{
          background: 'var(--el)', border: '1px solid var(--b)', padding: 12, borderRadius: 12,
          borderLeft: `3px solid ${status === 'ready' ? 'var(--g)' : 'var(--vl)'}`,
        }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>
            {status === 'ready' ? 'Foxhound Brief ready' : 'Building research report'}
          </div>
          <div style={{ color: 'var(--t2)', fontSize: 12, marginTop: 6, lineHeight: 1.6 }}>
            {(data.message as string) || 'Foxhound is preparing a deeper report for this application.'}
          </div>
          <ProcessContextCard context={context} action={nextAction} />
          <ActionRow>
            {briefHref(applicationId, true) && <ActionLink href={`/brief/${applicationId}`} label="Open Brief" emphasis />}
            {dossierId && <ActionLink href={`/dossier/${dossierId}`} label="Open Dossier" />}
            <ActionLink href="/applications" label="Open Tracker" />
          </ActionRow>
        </div>
      </div>
    );
  }

  if (toolName === 'interview_prep') {
    const company = data.company as string | undefined;
    const role = data.role as string | undefined;
    const status = data.status as string | undefined;
    const summary =
      (data.message as string | undefined) ||
      (typeof data.glassdoor === 'string' ? (data.glassdoor as string).slice(0, 220) : '');
    const courses = Array.isArray(data.courses)
      ? (data.courses as Array<Record<string, unknown>>)
      : [];
    const context = extractContext({
      ...data,
      company,
      role,
    });
    const nextAction = extractAction(data, context);
    return (
      <div style={{ padding: '3px 0' }}>
        <div style={{
          background: 'var(--el)', border: '1px solid var(--b)', padding: 12, borderRadius: 12,
          borderLeft: `3px solid ${status === 'found' ? 'var(--g)' : 'var(--warning)'}`,
        }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>
            {company ? `Interview prep — ${company}` : 'Interview prep'}
          </div>
          {role && (
            <div style={{ color: 'var(--t3)', fontSize: 12, marginTop: 2 }}>
              {role}
            </div>
          )}
          {summary && (
            <div style={{ color: 'var(--t2)', fontSize: 12, marginTop: 6, lineHeight: 1.6 }}>
              {summary}
            </div>
          )}
          {courses.length > 0 && (
            <div
              style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: '1px solid var(--b)',
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  color: 'var(--vl)',
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  marginBottom: 6,
                }}
              >
                Recommended Courses
              </div>
              <div style={{ display: 'grid', gap: 6 }}>
                {courses.slice(0, 3).map((course, idx) => {
                  const title = typeof course.title === 'string' ? course.title : 'Course';
                  const provider = typeof course.provider === 'string' ? course.provider : '';
                  const url = typeof course.url === 'string' ? course.url : '';
                  const reason = typeof course.reason === 'string' ? course.reason : '';
                  return (
                    <div
                      key={`${title}-${idx}`}
                      style={{
                        padding: '6px 8px',
                        borderRadius: 6,
                        border: '1px solid var(--b)',
                        background: 'rgba(255,255,255,0.02)',
                      }}
                    >
                      {url ? (
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: 'var(--vl)', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}
                        >
                          {title}
                        </a>
                      ) : (
                        <div style={{ color: 'var(--t)', fontSize: 12, fontWeight: 600 }}>{title}</div>
                      )}
                      {provider && (
                        <div style={{ fontSize: 10, color: 'var(--t3)', marginTop: 2 }}>{provider}</div>
                      )}
                      {reason && (
                        <div style={{ fontSize: 11, color: 'var(--t2)', marginTop: 4, lineHeight: 1.5 }}>{reason}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          <ProcessContextCard context={context} action={nextAction} />
          <ActionRow>
            {company && (
              <ActionLink
                href={seededIntelligenceHref('interview', { company, role })}
                label="Open Interview Prep"
                emphasis
              />
            )}
            <ActionLink href="/applications" label="Open Tracker" />
          </ActionRow>
        </div>
      </div>
    );
  }

  if (toolName === 'get_profile') {
    return (
      <div style={{ padding: '3px 0' }}>
        <div style={{ background: 'var(--el)', border: '1px solid var(--b)', padding: 10, borderRadius: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{data.name as string}</div>
          <div style={{ color: 'var(--t3)', fontSize: 12, marginTop: 1 }}>
            {data.location as string} — {data.tier as string} tier
          </div>
          {Array.isArray(data.skills) && (
            <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {(data.skills as string[]).slice(0, 6).map((s) => (
                <span key={s} style={{
                  background: 'rgba(255,255,255,0.05)', border: '1px solid var(--b)',
                  borderRadius: 5, padding: '1px 6px', fontSize: 11, color: 'var(--t3)',
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
      <div style={{ padding: '3px 0', fontSize: 12, color: 'var(--g)' }}>
        Updated: {(data.changes as string[]).join(', ')}
      </div>
    );
  }

  return null;
}

// ─── Screenshot Thumbnails ───

function ScreenshotRow({ preScreenshot, postScreenshot }: {
  preScreenshot?: string;
  postScreenshot?: string;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const handleOpen = useCallback((src: string) => {
    setExpanded(src);
  }, []);

  const handleClose = useCallback(() => {
    setExpanded(null);
  }, []);

  return (
    <>
      <div style={{
        marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--b)',
        display: 'flex', gap: 10,
      }}>
        {preScreenshot && (
          <ScreenshotThumb
            src={storageUrl(preScreenshot)}
            label="Filled Form"
            onOpen={handleOpen}
          />
        )}
        {postScreenshot && (
          <ScreenshotThumb
            src={storageUrl(postScreenshot)}
            label="Confirmation"
            onOpen={handleOpen}
          />
        )}
      </div>

      {/* Lightbox overlay */}
      {expanded && (
        <div
          role="dialog"
          aria-label="Screenshot preview"
          onClick={handleClose}
          onKeyDown={(e) => { if (e.key === 'Escape') handleClose(); }}
          tabIndex={0}
          style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            background: 'rgba(0,0,0,0.85)', display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            cursor: 'zoom-out', padding: 24,
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={expanded}
            alt="Screenshot full view"
            style={{
              maxWidth: '90vw', maxHeight: '90vh',
              borderRadius: 8, objectFit: 'contain',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
            }}
          />
        </div>
      )}
    </>
  );
}

function ScreenshotThumb({ src, label, onOpen }: {
  src: string;
  label: string;
  onOpen: (src: string) => void;
}) {
  const [error, setError] = useState(false);

  if (error) return null;

  return (
    <button
      type="button"
      onClick={() => onOpen(src)}
      aria-label={`View ${label} screenshot`}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        background: 'none', border: 'none', padding: 0, cursor: 'zoom-in',
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={label}
        onError={() => setError(true)}
        style={{
          width: 80, height: 56, objectFit: 'cover', borderRadius: 6,
          border: '1px solid var(--b)', background: 'var(--bg)',
          transition: 'border-color 0.15s',
        }}
        onMouseOver={(e) => (e.currentTarget.style.borderColor = 'var(--vl)')}
        onMouseOut={(e) => (e.currentTarget.style.borderColor = 'var(--b)')}
      />
      <span style={{
        fontSize: 9, color: 'var(--t3)', fontFamily: 'var(--font-mono)',
        letterSpacing: '0.04em', textTransform: 'uppercase',
      }}>
        {label}
      </span>
    </button>
  );
}

// ─── Question Form (collect all answers, submit together) ───

function QuestionForm({ questions, onSend }: {
  questions: Array<Record<string, unknown>>;
  onSend?: (message: string) => void;
}) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  function setAnswer(idx: number, value: string) {
    setAnswers((prev) => ({ ...prev, [idx]: value }));
  }

  function handleConfirmSubmit() {
    if (!onSend) return;
    // Build a single message with all answers
    const lines = questions.map((q) => {
      const idx = q.index as number;
      return `"${String(q.question)}": ${answers[idx]}`;
    });
    onSend(`Here are my answers:\n${lines.join('\n')}`);
    setSubmitted(true);
  }

  if (submitted) {
    return (
      <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--b)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 0' }}>
          <span style={{ color: 'var(--g)', fontSize: 14 }}>&#10003;</span>
          <span style={{ fontSize: 12, color: 'var(--g)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            Answers submitted
          </span>
        </div>
      </div>
    );
  }

  if (confirming) {
    return (
      <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--b)' }}>
        <div style={{ fontSize: 11, color: 'var(--vl)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 8 }}>
          Confirm your answers
        </div>
        {questions.map((q) => {
          const idx = q.index as number;
          return (
            <div key={idx} style={{ padding: '4px 0', borderBottom: '1px solid var(--b)' }}>
              <div style={{ fontSize: 11, color: 'var(--t3)' }}>{String(q.question)}</div>
              <div style={{ fontSize: 12, color: 'var(--t)', fontWeight: 500, marginTop: 2 }}>{answers[idx]}</div>
            </div>
          );
        })}
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button
            onClick={handleConfirmSubmit}
            style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.04em',
              textTransform: 'uppercase', padding: '6px 16px', borderRadius: 4,
              background: 'var(--g)', color: 'var(--bg)', border: 'none',
              cursor: 'pointer', fontWeight: 600,
            }}
          >
            Confirm & Submit
          </button>
          <button
            onClick={() => setConfirming(false)}
            style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.04em',
              textTransform: 'uppercase', padding: '6px 16px', borderRadius: 4,
              background: 'transparent', color: 'var(--t3)', border: '1px solid var(--b)',
              cursor: 'pointer',
            }}
          >
            Edit
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--b)' }}>
      <div style={{ fontSize: 11, color: 'var(--t3)', marginBottom: 6, fontFamily: 'var(--font-mono)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
        {questions.length} question{questions.length > 1 ? 's' : ''} need your input
      </div>
      {questions.map((q) => (
        <QuestionCard
          key={q.index as number}
          index={q.index as number}
          question={String(q.question)}
          draft={q.suggested_answer ? String(q.suggested_answer) : undefined}
          options={Array.isArray(q.options) ? (q.options as string[]) : undefined}
          fieldType={q.field_type ? String(q.field_type) : undefined}
          answer={answers[q.index as number] || ''}
          onAnswer={(val) => setAnswer(q.index as number, val)}
        />
      ))}
      <button
        onClick={() => setConfirming(true)}
        style={{
          width: '100%', marginTop: 10,
          fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.04em',
          textTransform: 'uppercase', padding: '8px 16px', borderRadius: 6,
          background: 'var(--v)',
          color: 'white',
          border: 'none',
          cursor: 'pointer', fontWeight: 600,
          transition: 'all 0.15s',
        }}
      >
        Review & Submit All
      </button>
    </div>
  );
}

// ─── Interactive Question Card ───

function QuestionCard({ question, draft, options, fieldType, answer, onAnswer }: {
  index: number;
  question: string;
  draft?: string;
  options?: string[];
  fieldType?: string;
  answer: string;
  onAnswer: (val: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(draft || '');

  const hasOptions = options && options.length > 0 && options.length <= 10;
  const isDropdown = (fieldType === 'select' || fieldType === 'radio') && hasOptions;
  const isAnswered = !!answer;

  // Answered — show compact
  if (isAnswered && !editing) {
    return (
      <div style={{
        padding: '6px 0', borderBottom: '1px solid var(--b)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: 'var(--g)', fontSize: 12 }}>&#10003;</span>
          <span style={{ fontSize: 11, color: 'var(--t3)' }}>{question}</span>
        </div>
        <button
          onClick={() => setEditing(true)}
          style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--t3)',
            background: 'none', border: 'none', cursor: 'pointer',
            textTransform: 'uppercase', letterSpacing: '0.04em',
          }}
        >
          Edit
        </button>
      </div>
    );
  }

  return (
    <div style={{ padding: '8px 0', borderBottom: '1px solid var(--b)' }}>
      <div style={{ fontSize: 12, color: 'var(--t)', fontWeight: 500, marginBottom: 6 }}>
        {question}
      </div>

      {/* Dropdown/radio — show clickable options */}
      {isDropdown && options && options.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onAnswer(opt); setEditing(false); }}
              style={{
                fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.03em',
                padding: '5px 12px', borderRadius: 6, cursor: 'pointer',
                background: answer === opt ? 'var(--vf)' : 'var(--bg)',
                border: `1px solid ${answer === opt ? 'var(--bv)' : 'var(--b)'}`,
                color: answer === opt ? 'var(--vl)' : 'var(--t2)',
                transition: 'all 0.15s',
              }}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      {/* Draft answer — approve or edit */}
      {draft && !isDropdown && !editing && (
        <div style={{
          background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8,
          padding: '8px 10px', marginTop: 4,
        }}>
          <div style={{ fontSize: 10, color: 'var(--vl)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 4 }}>
            Draft answer
          </div>
          <div style={{ fontSize: 12, color: 'var(--t2)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
            {draft}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              onClick={() => onAnswer(draft)}
              style={{
                fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.04em',
                textTransform: 'uppercase', padding: '4px 12px', borderRadius: 4,
                background: 'var(--g)', color: 'var(--bg)', border: 'none',
                cursor: 'pointer', fontWeight: 600,
              }}
            >
              Approve
            </button>
            <button
              onClick={() => setEditing(true)}
              style={{
                fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.04em',
                textTransform: 'uppercase', padding: '4px 12px', borderRadius: 4,
                background: 'transparent', color: 'var(--t3)', border: '1px solid var(--b)',
                cursor: 'pointer',
              }}
            >
              Edit
            </button>
          </div>
        </div>
      )}

      {/* Text input — for open-ended questions or editing */}
      {(editing || (!draft && !isDropdown)) && (
        <div style={{ marginTop: 4 }}>
          <textarea
            value={editText}
            onChange={(e) => { setEditText(e.target.value); }}
            placeholder="Type your answer..."
            style={{
              width: '100%', minHeight: 60, padding: '8px 10px',
              background: 'var(--bg)', border: '1px solid var(--b)', borderRadius: 8,
              color: 'var(--t)', fontSize: 12, lineHeight: 1.5, resize: 'vertical',
              fontFamily: 'var(--font-body)', outline: 'none',
            }}
            onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--bv)')}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = 'var(--b)';
              if (editText.trim()) onAnswer(editText.trim());
            }}
          />
        </div>
      )}
    </div>
  );
}

// ─── Helpers ───

function StatusBadge({ status }: { status: string }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 99,
      background: `${statusColor(status)}18`, color: statusColor(status),
      textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {(status || 'unknown').replace(/_/g, ' ')}
    </span>
  );
}

function statusColor(s: string): string {
  if (s === 'submitted') return 'var(--g)';
  if (s === 'scanning' || s === 'in_progress') return 'var(--vl)';
  if (s === 'waiting_user_input' || s === 'needs_manual') return 'var(--warning)';
  if (s === 'failed') return 'var(--error)';
  return 'var(--t3)';
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    scanning: 'Scanning form...', in_progress: 'Filling application...',
    submitted: 'Submitted', waiting_user_input: 'Needs your input',
    failed: 'Failed', needs_manual: 'Manual needed',
    all_answered: 'Submitting...',
  };
  if (!s) return 'Unknown';
  return map[s] || s.replace(/_/g, ' ');
}

function scoreColor(n: number): string {
  if (n >= 80) return 'var(--g)';
  if (n >= 60) return 'var(--vl)';
  return 'var(--t3)';
}
