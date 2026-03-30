'use client';

import { useState } from 'react';
import Link from 'next/link';

interface Props {
  toolName: string;
  data: Record<string, unknown>;
  onSend?: (message: string) => void;
}

export default function ToolResultCard({ toolName, data, onSend }: Props) {
  if (toolName === 'search_jobs' || toolName === 'get_matches') {
    const items = (data.jobs || data.matches || []) as Array<Record<string, unknown>>;
    if (items.length === 0) return null;

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
          {questions.length > 0 && (
            <QuestionForm questions={questions} onSend={onSend} />
          )}
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
    return (
      <div style={{ padding: '3px 0' }}>
        <div style={{ background: 'var(--el)', border: '1px solid var(--b)', padding: 10, borderRadius: 12 }}>
          {apps.slice(0, 5).map((app, i) => (
            <div key={app.application_id as string || i} style={{
              padding: '5px 0',
              borderBottom: i < Math.min(apps.length, 5) - 1 ? '1px solid var(--b)' : 'none',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12,
            }}>
              <span>{app.company as string} — {app.title as string}</span>
              <StatusBadge status={app.status as string} />
            </div>
          ))}
          <Link href="/applications" style={{
            display: 'block', textAlign: 'center', padding: '6px 0 0',
            fontSize: 12, color: 'var(--vl)',
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

// ─── Question Form (collect all answers, submit together) ───

function QuestionForm({ questions, onSend }: {
  questions: Array<Record<string, unknown>>;
  onSend?: (message: string) => void;
}) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const allAnswered = questions.every((q) => {
    const idx = q.index as number;
    return !!answers[idx]?.trim();
  });

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

  const isDropdown = fieldType === 'select' || fieldType === 'radio' || (options && options.length > 0);
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
