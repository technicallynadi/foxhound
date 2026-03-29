'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import ScrollReveal from '@/components/landing/ScrollReveal';
import { getProfile, getSettings, updatePreferences, updateAutopilot, updateNotifications, updateBlocklist } from '@/lib/api';

function Toggle({ label, desc, enabled, onChange }: { label: string; desc: string; enabled: boolean; onChange: () => void }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '16px 0', borderBottom: '1px solid var(--b)',
    }}>
      <div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>{desc}</div>
      </div>
      <button
        onClick={onChange}
        style={{
          width: 44, height: 24, borderRadius: 12, border: 'none', cursor: 'pointer',
          background: enabled ? 'var(--v)' : 'var(--b)',
          position: 'relative', transition: 'background 0.2s',
        }}
      >
        <span style={{
          width: 18, height: 18, borderRadius: '50%', background: 'white',
          position: 'absolute', top: 3,
          left: enabled ? 23 : 3,
          transition: 'left 0.2s',
        }} />
      </button>
    </div>
  );
}

function SettingInput({ label, placeholder, value, onChange }: { label: string; placeholder: string; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
      <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="input"
        style={{ width: '100%' }}
      />
    </div>
  );
}

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);

  // Job preferences (from profile)
  const [targetRoles, setTargetRoles] = useState('');
  const [targetLocations, setTargetLocations] = useState('');
  const [remotePref, setRemotePref] = useState('any');
  const [salaryFloor, setSalaryFloor] = useState('');
  const [seniority, setSeniority] = useState('');
  const [industries, setIndustries] = useState('');
  const [companySize, setCompanySize] = useState('');

  // Autopilot (from settings)
  const [autopilot, setAutopilot] = useState(false);
  const [threshold, setThreshold] = useState('75');
  const [dailyLimit, setDailyLimit] = useState('10');

  // Notifications (from settings)
  const [notifyApply, setNotifyApply] = useState(true);
  const [notifyDigest, setNotifyDigest] = useState(true);
  const [notifyChannel, setNotifyChannel] = useState('email');

  // Blocklist (from settings)
  const [blocklist, setBlocklist] = useState('');

  // Load from API on mount
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [profile, settings] = await Promise.allSettled([getProfile(), getSettings()]);

        if (!cancelled && profile.status === 'fulfilled') {
          const p = profile.value;
          setTargetRoles((p.target_titles || []).join(', '));
          setTargetLocations((p.target_locations || []).join(', '));
          setRemotePref(p.remote_preference || 'any');
          setSalaryFloor(p.salary_floor ? String(p.salary_floor) : '');
          setSeniority(p.seniority_level || '');
          setIndustries((p.industries || []).join(', '));
          setCompanySize(p.company_size_preference || '');
        }

        if (!cancelled && settings.status === 'fulfilled') {
          const s = settings.value as Record<string, Record<string, unknown>>;
          const ap = s.autopilot || {};
          setAutopilot(Boolean(ap.enabled));
          setThreshold(String(ap.threshold ?? 75));
          setDailyLimit(String(ap.daily_limit ?? 10));

          const n = s.notifications || {};
          setNotifyApply(n.on_apply !== false);
          setNotifyDigest(n.daily_digest !== false);
          const channels = (n.channels as string[]) || ['email'];
          setNotifyChannel(channels[0] || 'email');

          const bl = s.blocklist || {};
          setBlocklist(((bl.blacklist as string[]) || []).join(', '));
        }
      } catch {
        // API not available — fields stay at defaults
      }
      if (!cancelled) setLoading(false);
    }
    load();
    return () => { cancelled = true; };
  }, []);

  // Debounced save helper
  const debouncedSave = useCallback((fn: () => Promise<unknown>) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setSaving(true);
      setSaveMsg('');
      try {
        await fn();
        setSaveMsg('Saved');
        setTimeout(() => setSaveMsg(''), 2000);
      } catch {
        setSaveMsg('Failed to save');
      }
      setSaving(false);
    }, 800);
  }, []);

  // Save handlers — triggered on change
  function savePreferences(overrides: Record<string, unknown> = {}) {
    const prefs = {
      target_titles: (overrides.target_titles as string[] | undefined) ?? targetRoles.split(',').map(s => s.trim()).filter(Boolean),
      target_locations: (overrides.target_locations as string[] | undefined) ?? targetLocations.split(',').map(s => s.trim()).filter(Boolean),
      remote_preference: (overrides.remote_preference as string | undefined) ?? remotePref,
      salary_floor: parseInt((overrides.salary_floor as string | undefined) ?? salaryFloor, 10) || undefined,
      seniority_level: ((overrides.seniority_level as string | undefined) ?? seniority) || undefined,
      industries: (overrides.industries as string[] | undefined) ?? industries.split(',').map(s => s.trim()).filter(Boolean),
      company_size_preference: ((overrides.company_size_preference as string | undefined) ?? companySize) || undefined,
    };
    debouncedSave(() => updatePreferences(prefs));
  }

  function saveAutopilot(overrides: Record<string, unknown> = {}) {
    debouncedSave(() => updateAutopilot( {
      enabled: (overrides.enabled as boolean | undefined) ?? autopilot,
      threshold: parseInt((overrides.threshold as string | undefined) ?? threshold, 10) || 75,
      daily_limit: parseInt((overrides.daily_limit as string | undefined) ?? dailyLimit, 10) || 10,
    }));
  }

  function saveNotifications(overrides: Record<string, unknown> = {}) {
    debouncedSave(() => updateNotifications( {
      channels: [(overrides.channel as string | undefined) ?? notifyChannel],
      on_apply: (overrides.on_apply as boolean | undefined) ?? notifyApply,
      daily_digest: (overrides.daily_digest as boolean | undefined) ?? notifyDigest,
    }));
  }

  function saveBlocklist(value?: string) {
    const list = (value ?? blocklist).split(',').map(s => s.trim()).filter(Boolean);
    debouncedSave(() => updateBlocklist( { blacklist: list }));
  }

  if (loading) {
    return (
      <AuthGuard>
        <AppNav />
        <main style={{ paddingTop: 80, maxWidth: 600, margin: '0 auto', padding: '80px 20px 140px', textAlign: 'center' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t3)' }}>Loading settings...</div>
        </main>
      </AuthGuard>
    );
  }

  return (
    <AuthGuard>
      <AppNav />
      <main style={{ paddingTop: 80, maxWidth: 600, margin: '0 auto', padding: '80px 20px 140px', position: 'relative', zIndex: 1 }}>
        <ScrollReveal>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div className="section-label">Settings</div>
              <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', textTransform: 'uppercase' }}>
                SETTINGS
              </h1>
            </div>
            {(saving || saveMsg) && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: saving ? 'var(--t3)' : saveMsg === 'Saved' ? 'var(--g)' : 'var(--error, #f87171)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                {saving ? 'Saving...' : saveMsg}
              </div>
            )}
          </div>
        </ScrollReveal>

        {/* Job Preferences */}
        <ScrollReveal delay={1}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', marginTop: 32 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              01 / Job Preferences
            </div>
            <SettingInput label="Target roles" placeholder="Senior Backend Engineer, ML Engineer..." value={targetRoles} onChange={(v) => { setTargetRoles(v); savePreferences({ target_titles: v.split(',').map(s => s.trim()).filter(Boolean) }); }} />
            <SettingInput label="Target locations" placeholder="San Francisco, New York, Remote..." value={targetLocations} onChange={(v) => { setTargetLocations(v); savePreferences({ target_locations: v.split(',').map(s => s.trim()).filter(Boolean) }); }} />

            <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 10 }}>
                Remote preference
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                {[
                  { key: 'remote', label: 'Remote only' },
                  { key: 'hybrid', label: 'Hybrid' },
                  { key: 'any', label: 'Any' },
                ].map((opt) => (
                  <button key={opt.key} onClick={() => { setRemotePref(opt.key); savePreferences({ remote_preference: opt.key }); }} style={{
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

            <SettingInput label="Salary floor (USD)" placeholder="180000" value={salaryFloor} onChange={(v) => { setSalaryFloor(v); savePreferences({ salary_floor: v }); }} />

            <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 10 }}>
                Seniority level
              </label>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {[
                  { key: 'junior', label: 'Junior' },
                  { key: 'mid', label: 'Mid' },
                  { key: 'senior', label: 'Senior' },
                  { key: 'staff', label: 'Staff' },
                  { key: 'principal', label: 'Principal' },
                ].map((opt) => (
                  <button key={opt.key} onClick={() => { setSeniority(opt.key); savePreferences({ seniority_level: opt.key }); }} style={{
                    fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
                    padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${seniority === opt.key ? 'var(--bv)' : 'var(--b)'}`,
                    background: seniority === opt.key ? 'var(--vf)' : 'transparent',
                    color: seniority === opt.key ? 'var(--vl)' : 'var(--t3)', transition: 'all 0.2s',
                  }}>
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <SettingInput label="Industries" placeholder="AI/ML, FinTech, Developer Tools..." value={industries} onChange={(v) => { setIndustries(v); savePreferences({ industries: v.split(',').map(s => s.trim()).filter(Boolean) }); }} />

            <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 10 }}>
                Company size
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                {[
                  { key: 'startup', label: 'Startup' },
                  { key: 'mid', label: 'Mid-size' },
                  { key: 'enterprise', label: 'Enterprise' },
                  { key: 'any', label: 'Any' },
                ].map((opt) => (
                  <button key={opt.key} onClick={() => { setCompanySize(opt.key); savePreferences({ company_size_preference: opt.key }); }} style={{
                    fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
                    padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${companySize === opt.key ? 'var(--bv)' : 'var(--b)'}`,
                    background: companySize === opt.key ? 'var(--vf)' : 'transparent',
                    color: companySize === opt.key ? 'var(--vl)' : 'var(--t3)', transition: 'all 0.2s',
                  }}>
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ padding: '12px 0', fontSize: 12, color: 'var(--t3)' }}>
              Changes are saved automatically and affect your job matches.
            </div>
          </div>
        </ScrollReveal>

        {/* Autopilot */}
        <ScrollReveal delay={2}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', marginTop: 16 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              02 / Autopilot
            </div>
            <Toggle
              label="Autopilot mode"
              desc="Automatically apply to jobs above your match threshold"
              enabled={autopilot}
              onChange={() => { const next = !autopilot; setAutopilot(next); saveAutopilot({ enabled: next }); }}
            />
            <SettingInput label="Match threshold" placeholder="75" value={threshold} onChange={(v) => { setThreshold(v); saveAutopilot({ threshold: v }); }} />
            <SettingInput label="Daily application limit" placeholder="10" value={dailyLimit} onChange={(v) => { setDailyLimit(v); saveAutopilot({ daily_limit: v }); }} />
          </div>
        </ScrollReveal>

        {/* Notifications */}
        <ScrollReveal delay={2}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', marginTop: 16 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              03 / Notifications
            </div>
            <Toggle
              label="Application receipts"
              desc="Get notified when Foxhound submits an application"
              enabled={notifyApply}
              onChange={() => { const next = !notifyApply; setNotifyApply(next); saveNotifications({ on_apply: next }); }}
            />
            <Toggle
              label="Daily digest"
              desc="End-of-day summary of applications and new matches"
              enabled={notifyDigest}
              onChange={() => { const next = !notifyDigest; setNotifyDigest(next); saveNotifications({ daily_digest: next }); }}
            />
            <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 10 }}>
                Notification channel
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                {['slack', 'discord', 'sms', 'email'].map((ch) => (
                  <button
                    key={ch}
                    onClick={() => { setNotifyChannel(ch); saveNotifications({ channel: ch }); }}
                    style={{
                      fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
                      padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
                      border: `1px solid ${notifyChannel === ch ? 'var(--bv)' : 'var(--b)'}`,
                      background: notifyChannel === ch ? 'var(--vf)' : 'transparent',
                      color: notifyChannel === ch ? 'var(--vl)' : 'var(--t3)',
                      transition: 'all 0.2s',
                    }}
                  >
                    {ch}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* Blocklist */}
        <ScrollReveal delay={3}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', marginTop: 16 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              04 / Blocklist
            </div>
            <SettingInput
              label="Companies to skip"
              placeholder="Company A, Company B..."
              value={blocklist}
              onChange={(v) => { setBlocklist(v); saveBlocklist(v); }}
            />
            <div style={{ fontSize: 12, color: 'var(--t3)', padding: '12px 0' }}>
              Foxhound will never apply to these companies, even in autopilot mode.
            </div>
          </div>
        </ScrollReveal>

        {/* Account */}
        <ScrollReveal delay={4}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', marginTop: 16 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              05 / Account
            </div>
            <div style={{ padding: '16px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--b)' }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>Plan</div>
                <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>Beta — Free</div>
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                Active
              </span>
            </div>
            <div style={{ padding: '16px 0', display: 'flex', gap: 16 }}>
              <button style={{
                fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', background: 'none',
                border: '1px solid var(--b)', borderRadius: 6, padding: '8px 16px', cursor: 'pointer',
                letterSpacing: '0.04em', textTransform: 'uppercase',
              }}>
                Export data
              </button>
              <button style={{
                fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--error)', background: 'none',
                border: '1px solid rgba(248,113,113,0.15)', borderRadius: 6, padding: '8px 16px', cursor: 'pointer',
                letterSpacing: '0.04em', textTransform: 'uppercase',
              }}>
                Delete account
              </button>
            </div>
          </div>
        </ScrollReveal>
      </main>
    </AuthGuard>
  );
}
