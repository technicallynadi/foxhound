'use client';

import { useEffect, useState } from 'react';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import PageSkeleton from '@/components/PageSkeleton';
import ScrollReveal from '@/components/landing/ScrollReveal';
import { getProfile, updateProfile } from '@/lib/api';

interface Profile {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  portfolio_url: string;
  location: string;
  summary: string;
  skills: string[];
  experience: Array<{ company: string; title: string; start_date?: string; end_date?: string }>;
  education: Array<{ institution: string; degree: string; field?: string; year?: string }>;
  seniority_level: string | null;
  years_experience: number | null;
  archetype: string | null;
  resume_filename: string | null;
  onboarding_step: string;
  [key: string]: unknown;
}

function Field({ label, value, onChange, type = 'text', placeholder = '' }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; placeholder?: string;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
        letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 6,
      }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: '100%', padding: '10px 14px', borderRadius: 8,
          background: 'var(--bg)', border: '1px solid var(--b)',
          color: 'var(--t)', fontSize: 14, outline: 'none',
          transition: 'border-color 0.2s',
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--bv)'; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--b)'; }}
      />
    </div>
  );
}

function TextArea({ label, value, onChange, rows = 3, placeholder = '' }: {
  label: string; value: string; onChange: (v: string) => void; rows?: number; placeholder?: string;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
        letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 6,
      }}>
        {label}
      </label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        placeholder={placeholder}
        style={{
          width: '100%', padding: '10px 14px', borderRadius: 8,
          background: 'var(--bg)', border: '1px solid var(--b)',
          color: 'var(--t)', fontSize: 14, outline: 'none', resize: 'vertical',
          fontFamily: 'inherit', lineHeight: 1.6,
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--bv)'; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--b)'; }}
      />
    </div>
  );
}

function SkillTags({ skills, onChange }: { skills: string[]; onChange: (s: string[]) => void }) {
  const [input, setInput] = useState('');

  const addSkill = () => {
    const trimmed = input.trim();
    if (trimmed && !skills.includes(trimmed)) {
      onChange([...skills, trimmed]);
      setInput('');
    }
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
        letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 6,
      }}>
        Skills
      </label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {skills.map((s) => (
          <span key={s} style={{
            padding: '4px 10px', borderRadius: 6, fontSize: 12,
            background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.15)',
            color: 'var(--vl)', display: 'flex', alignItems: 'center', gap: 6,
          }}>
            {s}
            <button
              onClick={() => onChange(skills.filter(x => x !== s))}
              style={{
                background: 'none', border: 'none', color: 'var(--t3)',
                cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: 0,
              }}
              aria-label={`Remove ${s}`}
            >
              x
            </button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addSkill(); } }}
          placeholder="Add a skill..."
          style={{
            flex: 1, padding: '8px 12px', borderRadius: 8,
            background: 'var(--bg)', border: '1px solid var(--b)',
            color: 'var(--t)', fontSize: 13, outline: 'none',
          }}
        />
        <button onClick={addSkill} className="btn-ghost" style={{ height: 36, padding: '0 14px', fontSize: 12 }}>
          Add
        </button>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  // Editable fields
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [linkedinUrl, setLinkedinUrl] = useState('');
  const [portfolioUrl, setPortfolioUrl] = useState('');
  const [location, setLocation] = useState('');
  const [summary, setSummary] = useState('');
  const [skills, setSkills] = useState<string[]>([]);

  useEffect(() => {
    getProfile()
      .then((p) => {
        const data = p as unknown as Profile;
        setProfile(data);
        setFirstName(data.first_name || '');
        setLastName(data.last_name || '');
        setEmail(data.email || '');
        setPhone(data.phone || '');
        setLinkedinUrl(data.linkedin_url || '');
        setPortfolioUrl(data.portfolio_url || '');
        setLocation(data.location || '');
        setSummary(data.summary || '');
        setSkills(data.skills || []);
      })
      .catch(() => setError('No profile yet. Upload a resume to get started.'))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError('');
    try {
      await updateProfile({
        first_name: firstName,
        last_name: lastName,
        phone,
        linkedin_url: linkedinUrl,
        portfolio_url: portfolioUrl,
        location,
        summary,
        skills,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      setError('Failed to save. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <AuthGuard>
      <AppNav />
      <main style={{ paddingTop: 80, maxWidth: 1100, margin: '0 auto', padding: '80px var(--section-px, 20px) 140px', position: 'relative', zIndex: 1 }}>
        <ScrollReveal>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 8 }}>
            Profile
          </div>
        </ScrollReveal>
        <ScrollReveal delay={1}>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700, letterSpacing: '-0.03em', textTransform: 'uppercase' }}>
            Your Profile
          </h1>
          <p style={{ color: 'var(--t2)', fontSize: 14, marginTop: 4 }}>
            Foxhound fills applications using this info. Review it and fix anything that does not look right.
          </p>
        </ScrollReveal>

        {loading ? (
          <PageSkeleton variant="profile" />
        ) : error && !profile ? (
          <div style={{ marginTop: 40, padding: 20, borderRadius: 10, background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)', color: 'var(--error)', fontSize: 14 }}>
            {error}
          </div>
        ) : profile ? (
          <div style={{ marginTop: 32 }}>
            {/* Resume info */}
            {profile.resume_filename && (
              <ScrollReveal delay={2}>
                <div style={{
                  padding: '12px 16px', borderRadius: 8, marginBottom: 24,
                  background: 'rgba(139,92,246,0.04)', border: '1px solid rgba(139,92,246,0.1)',
                  fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--vl)',
                  display: 'flex', alignItems: 'center', gap: 8,
                }}>
                  Resume: {profile.resume_filename}
                </div>
              </ScrollReveal>
            )}

            {/* Personal info */}
            <ScrollReveal delay={2}>
              <div style={{
                background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                padding: 24, marginBottom: 20,
              }}>
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                  letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 16,
                }}>
                  Personal Information
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
                  <Field label="First Name" value={firstName} onChange={setFirstName} />
                  <Field label="Last Name" value={lastName} onChange={setLastName} />
                </div>
                <Field label="Email" value={email} onChange={setEmail} type="email" />
                <Field label="Phone" value={phone} onChange={setPhone} type="tel" placeholder="+1 555-000-0000" />
                <Field label="Location" value={location} onChange={setLocation} placeholder="San Francisco, CA" />
              </div>
            </ScrollReveal>

            {/* Links */}
            <ScrollReveal delay={3}>
              <div style={{
                background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                padding: 24, marginBottom: 20,
              }}>
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                  letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 16,
                }}>
                  Links
                </div>
                <Field label="LinkedIn" value={linkedinUrl} onChange={setLinkedinUrl} placeholder="https://linkedin.com/in/..." />
                <Field label="Portfolio / GitHub" value={portfolioUrl} onChange={setPortfolioUrl} placeholder="https://github.com/..." />
              </div>
            </ScrollReveal>

            {/* Summary */}
            <ScrollReveal delay={3}>
              <div style={{
                background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                padding: 24, marginBottom: 20,
              }}>
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                  letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 16,
                }}>
                  Professional Summary
                </div>
                <TextArea label="Summary" value={summary} onChange={setSummary} rows={4} placeholder="Brief professional summary..." />
              </div>
            </ScrollReveal>

            {/* Skills */}
            <ScrollReveal delay={3}>
              <div style={{
                background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                padding: 24, marginBottom: 20,
              }}>
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                  letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 16,
                }}>
                  Skills
                </div>
                <SkillTags skills={skills} onChange={setSkills} />
              </div>
            </ScrollReveal>

            {/* Experience (read-only for now) */}
            {profile.experience && profile.experience.length > 0 && (
              <ScrollReveal delay={3}>
                <div style={{
                  background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                  padding: 24, marginBottom: 20,
                }}>
                  <div style={{
                    fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                    letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 16,
                  }}>
                    Experience
                  </div>
                  {(profile.experience as Array<{ company: string; title: string; start_date?: string; end_date?: string }>).map((exp, i) => (
                    <div key={i} style={{
                      padding: '12px 0',
                      borderBottom: i < profile.experience.length - 1 ? '1px solid var(--b)' : 'none',
                    }}>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{exp.title}</div>
                      <div style={{ fontSize: 13, color: 'var(--t2)', marginTop: 2 }}>{exp.company}</div>
                      {(exp.start_date || exp.end_date) && (
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', marginTop: 4 }}>
                          {exp.start_date || '?'} — {exp.end_date || 'Present'}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </ScrollReveal>
            )}

            {/* Education (read-only for now) */}
            {profile.education && profile.education.length > 0 && (
              <ScrollReveal delay={3}>
                <div style={{
                  background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12,
                  padding: 24, marginBottom: 20,
                }}>
                  <div style={{
                    fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                    letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 16,
                  }}>
                    Education
                  </div>
                  {(profile.education as Array<{ institution: string; degree: string; field?: string; year?: string }>).map((edu, i) => (
                    <div key={i} style={{ padding: '12px 0', borderBottom: i < profile.education.length - 1 ? '1px solid var(--b)' : 'none' }}>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{edu.degree}{edu.field ? `, ${edu.field}` : ''}</div>
                      <div style={{ fontSize: 13, color: 'var(--t2)', marginTop: 2 }}>{edu.institution}{edu.year ? ` · ${edu.year}` : ''}</div>
                    </div>
                  ))}
                </div>
              </ScrollReveal>
            )}

            {/* Save button */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 24 }}>
              <button
                onClick={handleSave}
                disabled={saving}
                className="btn-solid"
                style={{ cursor: saving ? 'wait' : 'pointer' }}
              >
                {saving ? 'Saving...' : 'Save Changes'}
              </button>
              {saved && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--g)' }}>Saved</span>
              )}
              {error && profile && (
                <span style={{ fontSize: 13, color: 'var(--error)' }}>{error}</span>
              )}
            </div>
          </div>
        ) : null}
      </main>
    </AuthGuard>
  );
}
