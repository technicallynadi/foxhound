'use client';

import { useCallback, useEffect, useState } from 'react';
import { getPendingQuestions, submitAnswers, listApplications } from '@/lib/api';

interface Question {
  index: number;
  question: string;
  field_type: string;
  category: string;
  suggested_answer?: string;
  options?: string[];
}

interface Props {
  applicationId: string;
  allAppIds?: string[];
  isOpen?: boolean;
  onClose: () => void;
  onSubmitted?: () => void;
  onSwitchApp?: (appId: string) => void;
}

export default function QuestionReviewPanel({ applicationId, allAppIds, isOpen = true, onClose, onSubmitted }: Props) {
  const [activeAppId, setActiveAppId] = useState(applicationId);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [jobInfoMap, setJobInfoMap] = useState<Record<string, { company: string; title: string }>>({});
  const [tabs] = useState<string[]>(allAppIds && allAppIds.length > 1 ? [...allAppIds] : []);
  const jobInfo = jobInfoMap[activeAppId] || null;

  // Sync if parent changes applicationId (e.g. opening from a different event)
  useEffect(() => { setActiveAppId(applicationId); }, [activeAppId]);

  // Fetch job info once on mount — never re-run
  useEffect(() => {
    listApplications({ status: 'waiting_user_input', per_page: 50 })
      .then((apps) => {
        const map: Record<string, { company: string; title: string }> = {};
        ((apps as { items: Array<{ id: string; job: { company: string; title: string } }> }).items || []).forEach((a) => {
          if (a.job) map[a.id] = { company: a.job.company, title: a.job.title };
        });
        setJobInfoMap(map);
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch questions when applicationId changes
  useEffect(() => {
    setLoading(true);
    setError('');

    getPendingQuestions(activeAppId)
      .then((data) => {
        setQuestions(data.questions);
        const prefill: Record<number, string> = {};
        data.questions.forEach((q) => {
          if (q.suggested_answer) prefill[q.index] = q.suggested_answer;
        });
        setAnswers(prefill);
      })
      .catch(() => setError('Could not load questions.'))
      .finally(() => setLoading(false));
  }, [activeAppId]);

  const handleSubmit = useCallback(async () => {
    setSubmitting(true);
    setError('');
    try {
      const payload = questions.map((q) => {
        const userAnswer = answers[q.index];
        if (q.suggested_answer && userAnswer === q.suggested_answer) {
          return { index: q.index, action: 'approve' };
        }
        return { index: q.index, action: 'answer', answer: userAnswer || '' };
      });
      await submitAnswers(activeAppId, payload);
      onSubmitted?.();
      onClose();
    } catch {
      setError('Failed to submit. Please try again.');
    }
    setSubmitting(false);
  }, [applicationId, questions, answers, onClose, onSubmitted]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose, isOpen]);

  if (!isOpen || !applicationId) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 200,
        background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)',
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--sf)', border: '1px solid var(--bv)',
          borderRadius: 16, width: '100%', maxWidth: 560,
          maxHeight: '80vh', display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '16px 24px', borderBottom: '1px solid var(--b)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Review Answers
            </div>
            {jobInfo && (
              <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>
                {jobInfo.company} — {jobInfo.title}
              </div>
            )}
            <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>
              {questions.length} question{questions.length !== 1 ? 's' : ''} need your input
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: 'var(--t3)',
            fontSize: 18, cursor: 'pointer',
          }}>
            &times;
          </button>
        </div>

        {/* App tabs — only when multiple apps have questions */}
        {tabs.length > 1 && (
          <div style={{
            display: 'flex', gap: 0, borderBottom: '1px solid var(--b)',
            overflowX: 'auto',
          }}>
            {tabs.map((id, i) => (
              <button
                key={id}
                onClick={() => setActiveAppId(id)}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10,
                  color: id === activeAppId ? 'var(--vl)' : 'var(--t3)',
                  textTransform: 'uppercase', letterSpacing: '0.04em',
                  padding: '10px 16px', background: 'none', border: 'none',
                  borderBottom: id === activeAppId ? '2px solid var(--v)' : '2px solid transparent',
                  cursor: 'pointer', whiteSpace: 'nowrap',
                }}
              >
                {jobInfoMap[id]?.company || `App ${i + 1}`}
              </button>
            ))}
          </div>
        )}

        {/* Questions */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
          {loading ? (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t3)', padding: '24px 0', textAlign: 'center' }}>
              Loading questions...
            </div>
          ) : questions.length === 0 ? (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t3)', padding: '24px 0', textAlign: 'center' }}>
              No pending questions.
            </div>
          ) : (
            questions.map((q) => (
              <div key={q.index} style={{ marginBottom: 16, paddingBottom: 16, borderBottom: '1px solid var(--b)' }}>
                <label style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                  textTransform: 'uppercase', letterSpacing: '0.06em',
                  display: 'block', marginBottom: 6,
                }}>
                  Q{q.index + 1}
                </label>
                <div style={{ fontSize: 14, color: 'var(--t)', marginBottom: 8 }}>
                  {q.question}
                </div>
                {q.options && q.options.length > 0 ? (
                  <select
                    value={answers[q.index] || ''}
                    onChange={(e) => setAnswers((prev) => ({ ...prev, [q.index]: e.target.value }))}
                    className="input"
                    style={{ width: '100%' }}
                  >
                    <option value="">Select...</option>
                    {q.options.map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : (
                  <textarea
                    value={answers[q.index] || ''}
                    onChange={(e) => setAnswers((prev) => ({ ...prev, [q.index]: e.target.value }))}
                    className="input"
                    style={{ width: '100%', minHeight: 60, resize: 'vertical' }}
                    placeholder={q.suggested_answer ? 'Foxhound drafted this — edit or approve' : 'Your answer'}
                  />
                )}
                {q.suggested_answer && answers[q.index] === q.suggested_answer && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--g)', marginTop: 4 }}>
                    Foxhound&apos;s draft — will be approved as-is
                  </div>
                )}
              </div>
            ))
          )}

          {error && (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--error)', marginTop: 8 }}>
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        {questions.length > 0 && (
          <div style={{
            padding: '12px 24px', borderTop: '1px solid var(--b)',
            display: 'flex', justifyContent: 'flex-end', gap: 8,
          }}>
            <button onClick={onClose} style={{
              fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
              textTransform: 'uppercase', letterSpacing: '0.04em',
              padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
              border: '1px solid var(--b)', background: 'transparent',
            }}>
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="btn-solid"
              style={{ fontSize: 12 }}
            >
              {submitting ? 'Submitting...' : 'Approve & Submit'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
