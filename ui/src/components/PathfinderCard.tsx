'use client';

import { useState } from 'react';

export interface PathfinderData {
  manager_signals?: {
    likely_title?: string | null;
    likely_name?: string | null;
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
  confirmed_manager?: {
    name?: string;
    title?: string;
    linkedin_url?: string;
  } | null;
  error?: string;
}

interface PathfinderCardProps {
  jobId: string | null;
  initialData: PathfinderData | null;
  companyName: string;
  jobTitle?: string;
}

const mono = { fontFamily: 'var(--font-mono)' };

export default function PathfinderCard({ jobId, initialData, companyName, jobTitle }: PathfinderCardProps) {
  const [data, setData] = useState<PathfinderData | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const manager = data?.confirmed_manager || data?.manager_signals;
  const managerName = data?.confirmed_manager?.name || data?.manager_signals?.likely_name;
  const managerTitle = data?.confirmed_manager?.title || data?.manager_signals?.likely_title;
  const department = data?.manager_signals?.department;

  const handleRun = async () => {
    if (!jobId || loading) return;
    setLoading(true);
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('foxhound_token') : null;
      const res = await fetch(`/api/v1/pathfinder/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok) throw new Error('Pathfinder request failed');
      const result = await res.json();
      setData(result);
    } catch {
      // silent — user can retry
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 1500);
  };

  if (!data && !loading) {
    return (
      <div style={{ padding: '12px 0', textAlign: 'center' }}>
        <p style={{ fontSize: 13, color: 'var(--t3)', marginBottom: 10 }}>
          Find the likely hiring manager at {companyName} and draft outreach messages.
        </p>
        {jobId && (
          <button
            onClick={handleRun}
            style={{
              ...mono, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em',
              padding: '6px 16px', borderRadius: 4, cursor: 'pointer',
              background: 'var(--accent)', color: '#fff', border: 'none',
            }}
          >
            Run Pathfinder
          </button>
        )}
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ padding: '16px 0', textAlign: 'center' }}>
        <div style={{
          width: 20, height: 20, border: '2px solid var(--b)', borderTopColor: 'var(--accent)',
          borderRadius: '50%', animation: 'spin 0.8s linear infinite', margin: '0 auto 10px',
        }} />
        <p style={{ ...mono, fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase' }}>
          Discovering hiring manager...
        </p>
      </div>
    );
  }

  if (data?.error) {
    return (
      <div style={{ padding: '12px 0' }}>
        <p style={{ fontSize: 13, color: 'var(--r, #ef4444)' }}>
          Pathfinder could not complete: {data.error}
        </p>
        {jobId && (
          <button
            onClick={handleRun}
            style={{
              ...mono, fontSize: 10, textTransform: 'uppercase', marginTop: 8,
              padding: '4px 12px', borderRadius: 3, cursor: 'pointer',
              background: 'transparent', border: '1px solid var(--b)', color: 'var(--t3)',
            }}
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div style={{ padding: '4px 0' }}>
      {/* Manager signals */}
      {manager && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 13, color: 'var(--t3)', marginBottom: 4 }}>
            Likely hiring manager
          </div>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--t)' }}>
            {managerName || 'Unknown'}{managerTitle ? ` — ${managerTitle}` : ''}
          </div>
          {department && (
            <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 2 }}>{department}</div>
          )}
          {data?.confirmed_manager?.linkedin_url && (
            <a
              href={data.confirmed_manager.linkedin_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ ...mono, fontSize: 10, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 4, display: 'inline-block' }}
            >
              View LinkedIn &rarr;
            </a>
          )}
        </div>
      )}

      {/* Search URLs */}
      {data?.search_urls?.linkedin && !data?.confirmed_manager?.linkedin_url && (
        <div style={{ marginBottom: 14 }}>
          <a
            href={data.search_urls.linkedin}
            target="_blank"
            rel="noopener noreferrer"
            style={{ ...mono, fontSize: 10, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em' }}
          >
            Search LinkedIn &rarr;
          </a>
        </div>
      )}

      {/* Overlap */}
      {data?.overlap?.summary_for_outreach && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ ...mono, fontSize: 10, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
            Your connection
          </div>
          <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.5 }}>
            {data.overlap.summary_for_outreach}
          </div>
        </div>
      )}

      {/* Outreach drafts */}
      {data?.outreach && (data.outreach.linkedin_note || data.outreach.email_body) && (
        <div>
          <div style={{ ...mono, fontSize: 10, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
            Outreach drafts
          </div>

          {data.outreach.linkedin_note && (
            <div style={{
              background: 'var(--vf)', border: '1px solid var(--bv)',
              borderRadius: 4, padding: '10px 12px', marginBottom: 8, position: 'relative',
            }}>
              <div style={{ ...mono, fontSize: 9, color: 'var(--t3)', textTransform: 'uppercase', marginBottom: 4 }}>
                LinkedIn note
              </div>
              <div style={{ fontSize: 13, color: 'var(--t)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                {data.outreach.linkedin_note}
              </div>
              <button
                onClick={() => copyToClipboard(data.outreach!.linkedin_note!, 'linkedin')}
                style={{
                  ...mono, position: 'absolute', top: 8, right: 8, fontSize: 9,
                  textTransform: 'uppercase', padding: '2px 8px', borderRadius: 3, cursor: 'pointer',
                  background: 'transparent', border: '1px solid var(--b)', color: 'var(--t3)',
                }}
              >
                {copiedField === 'linkedin' ? 'Copied' : 'Copy'}
              </button>
            </div>
          )}

          {data.outreach.email_body && (
            <div style={{
              background: 'var(--vf)', border: '1px solid var(--bv)',
              borderRadius: 4, padding: '10px 12px', position: 'relative',
            }}>
              <div style={{ ...mono, fontSize: 9, color: 'var(--t3)', textTransform: 'uppercase', marginBottom: 4 }}>
                {data.outreach.email_subject ? `Email — ${data.outreach.email_subject}` : 'Email'}
              </div>
              <div style={{ fontSize: 13, color: 'var(--t)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                {data.outreach.email_body}
              </div>
              <button
                onClick={() => copyToClipboard(data.outreach!.email_body!, 'email')}
                style={{
                  ...mono, position: 'absolute', top: 8, right: 8, fontSize: 9,
                  textTransform: 'uppercase', padding: '2px 8px', borderRadius: 3, cursor: 'pointer',
                  background: 'transparent', border: '1px solid var(--b)', color: 'var(--t3)',
                }}
              >
                {copiedField === 'email' ? 'Copied' : 'Copy'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
