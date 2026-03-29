'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import Link from 'next/link';
import { uploadResume, updateProfile, updatePreferences } from '@/lib/api';

type Step = 1 | 2 | 3;

const ARCHETYPES = [
  { id: 'tech', label: 'Tech', desc: 'Engineering, SWE, DevOps, ML/AI' },
  { id: 'business', label: 'Business', desc: 'Product, Strategy, Ops, Marketing' },
  { id: 'design', label: 'Design', desc: 'UX, Product Design, Brand' },
  { id: 'science', label: 'Science', desc: 'Research, Biotech, Climate' },
  { id: 'finance', label: 'Finance', desc: 'Quant, FinTech, Trading' },
  { id: 'startup', label: 'Startup', desc: 'Founding roles, generalist' },
  { id: 'executive', label: 'Executive', desc: 'C-suite, VP, Director' },
];

export default function OnboardPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [archetype, setArchetype] = useState('');
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Step 3 form state
  const [remotePref, setRemotePref] = useState('');
  const [locations, setLocations] = useState('');
  const [salaryFloor, setSalaryFloor] = useState('');

  async function handleUpload(file: File) {
    setUploading(true);
    setError('');
    try {
      await uploadResume(file);
      setStep(2);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    }
    setUploading(false);
  }

  async function handleArchetypeContinue() {
    if (!archetype) return;
    setSaving(true);
    setError('');
    try {
      await updateProfile({ archetype });
      setStep(3);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save');
    }
    setSaving(false);
  }

  async function handleComplete() {
    setSaving(true);
    setError('');
    try {
      const prefs: Record<string, unknown> = {};
      if (remotePref) prefs.remote_preference = remotePref;
      if (locations.trim()) prefs.target_locations = locations.split(',').map((s: string) => s.trim()).filter(Boolean);
      if (salaryFloor.trim()) prefs.salary_floor = parseInt(salaryFloor.replace(/[^0-9]/g, ''), 10) || undefined;

      if (Object.keys(prefs).length > 0) {
        await updatePreferences(prefs as Parameters<typeof updatePreferences>[0]);
      }
      router.push('/dashboard');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save');
      setSaving(false);
    }
  }

  return (
    <AuthGuard>
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', padding: '80px 20px', position: 'relative', zIndex: 1,
      }}>
        {/* Progress */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 48 }}>
          {[1, 2, 3].map((s) => (
            <div key={s} style={{
              width: s === step ? 32 : 8, height: 4, borderRadius: 2,
              background: s <= step ? 'var(--v)' : 'var(--b)',
              transition: 'all 0.3s',
            }} />
          ))}
        </div>

        {/* Error banner */}
        {error && (
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--error, #f87171)',
            background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.15)',
            borderRadius: 8, padding: '10px 16px', marginBottom: 24, maxWidth: 480, textAlign: 'center',
          }}>
            {error}
          </div>
        )}

        {/* Step 1: Upload Resume */}
        {step === 1 && (
          <div style={{ textAlign: 'center', maxWidth: 480 }}>
            <div className="section-label">01 / Resume</div>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 32, fontWeight: 700, letterSpacing: '-0.03em', textTransform: 'uppercase', marginTop: 8 }}>
              UPLOAD YOUR <span style={{ color: 'var(--v)' }}>RESUME</span>
            </h1>
            <p style={{ fontSize: 15, color: 'var(--t2)', lineHeight: 1.7, marginTop: 12 }}>
              PDF only. We&apos;ll extract your skills, experience, and preferences in seconds.
            </p>

            <label style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              marginTop: 32, padding: '48px 32px',
              background: 'var(--sf)', border: '2px dashed var(--b)', borderRadius: 12,
              cursor: 'pointer', transition: 'border-color 0.3s',
            }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--bv)')}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--b)')}
            >
              <input type="file" accept=".pdf" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])} />
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--vl)', marginBottom: 8 }}>
                {uploading ? 'Parsing...' : 'Drop PDF here or click to browse'}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)' }}>
                Max 10MB
              </div>
            </label>
          </div>
        )}

        {/* Step 2: Pick Archetype */}
        {step === 2 && (
          <div style={{ textAlign: 'center', maxWidth: 560 }}>
            <div className="section-label">02 / Career Focus</div>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 32, fontWeight: 700, letterSpacing: '-0.03em', textTransform: 'uppercase', marginTop: 8 }}>
              PICK YOUR <span style={{ color: 'var(--v)' }}>AGENT</span>
            </h1>
            <p style={{ fontSize: 15, color: 'var(--t2)', lineHeight: 1.7, marginTop: 12 }}>
              This shapes how Foxhound searches, evaluates, and preps you.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8, marginTop: 32 }}>
              {ARCHETYPES.map((a) => (
                <button
                  key={a.id}
                  onClick={() => setArchetype(a.id)}
                  style={{
                    padding: '16px 14px', borderRadius: 10, cursor: 'pointer', textAlign: 'left',
                    background: archetype === a.id ? 'var(--vf)' : 'var(--sf)',
                    border: `1px solid ${archetype === a.id ? 'var(--bv)' : 'var(--b)'}`,
                    transition: 'all 0.2s',
                  }}
                >
                  <div style={{ fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600, color: archetype === a.id ? 'var(--t)' : 'var(--t2)' }}>
                    {a.label}
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', marginTop: 4, letterSpacing: '0.02em' }}>
                    {a.desc}
                  </div>
                </button>
              ))}
            </div>

            <button
              onClick={handleArchetypeContinue}
              disabled={!archetype || saving}
              className="btn-solid"
              style={{ marginTop: 32, opacity: archetype && !saving ? 1 : 0.4, cursor: archetype && !saving ? 'pointer' : 'not-allowed' }}
            >
              {saving ? 'Saving...' : 'Continue →'}
            </button>
          </div>
        )}

        {/* Step 3: Preferences */}
        {step === 3 && (
          <div style={{ textAlign: 'center', maxWidth: 480 }}>
            <div className="section-label">03 / Preferences</div>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 32, fontWeight: 700, letterSpacing: '-0.03em', textTransform: 'uppercase', marginTop: 8 }}>
              ALMOST <span style={{ color: 'var(--v)' }}>THERE</span>
            </h1>
            <p style={{ fontSize: 15, color: 'var(--t2)', lineHeight: 1.7, marginTop: 12 }}>
              You can fine-tune these anytime in Settings or by talking to your agent.
            </p>

            <div style={{ marginTop: 32, textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 6 }}>
                  Remote preference
                </label>
                <div style={{ display: 'flex', gap: 8 }}>
                  {[
                    { key: 'remote', label: 'Remote only' },
                    { key: 'hybrid', label: 'Hybrid' },
                    { key: 'any', label: 'Any' },
                  ].map((opt) => (
                    <button key={opt.key} onClick={() => setRemotePref(opt.key)} style={{
                      fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
                      padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
                      border: `1px solid ${remotePref === opt.key ? 'var(--bv)' : 'var(--b)'}`,
                      background: remotePref === opt.key ? 'var(--vf)' : 'transparent',
                      color: remotePref === opt.key ? 'var(--vl)' : 'var(--t3)', transition: 'all 0.2s',
                    }}>
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 6 }}>
                  Target locations
                </label>
                <input
                  type="text"
                  value={locations}
                  onChange={(e) => setLocations(e.target.value)}
                  placeholder="San Francisco, New York, Remote..."
                  className="input"
                  style={{ width: '100%' }}
                />
              </div>
              <div>
                <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 6 }}>
                  Salary floor
                </label>
                <input
                  type="text"
                  value={salaryFloor}
                  onChange={(e) => setSalaryFloor(e.target.value)}
                  placeholder="$150,000"
                  className="input"
                  style={{ width: '100%' }}
                />
              </div>
            </div>

            <button onClick={handleComplete} disabled={saving} className="btn-solid" style={{ marginTop: 32 }}>
              {saving ? 'Saving...' : 'Start Finding Jobs →'}
            </button>
            <div style={{ marginTop: 12 }}>
              <button onClick={() => router.push('/dashboard')} style={{ background: 'none', border: 'none', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Skip for now
              </button>
            </div>
          </div>
        )}

        {/* Bottom link */}
        <div style={{ position: 'absolute', bottom: 32, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', letterSpacing: '0.04em' }}>
          <Link href="/" style={{ color: 'inherit' }}>← Back to Foxhound</Link>
        </div>
      </div>
    </AuthGuard>
  );
}
