'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import PageSkeleton from '@/components/PageSkeleton';
import ScrollReveal from '@/components/landing/ScrollReveal';
import { getProfile, getSettings, updateProfile, updatePreferences, updateAutopilot, updateNotifications, updateBlocklist } from '@/lib/api';

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

function SettingSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
      <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input"
        style={{ width: '100%' }}
      >
        <option value="">Select...</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}

function AutonomyMeter({ enabled, threshold }: { enabled: boolean; threshold: number }) {
  const level = !enabled ? 'Manual' : threshold >= 85 ? 'Conservative' : threshold >= 70 ? 'Balanced' : 'Aggressive';
  const pct = !enabled ? 10 : threshold >= 85 ? 35 : threshold >= 70 ? 65 : 88;

  return (
    <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
      <div style={{ fontSize: 14, fontWeight: 500 }}>Autonomy level: {level}</div>
      <div style={{ marginTop: 10, height: 4, borderRadius: 999, background: 'var(--b)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'linear-gradient(90deg, var(--t3), var(--v))' }} />
      </div>
      <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 10, lineHeight: 1.6 }}>
        {!enabled
          ? 'Foxhound finds jobs and waits for you to decide.'
          : threshold >= 85
            ? 'Foxhound only applies to near-perfect fits. Everything else waits for you.'
            : threshold >= 70
              ? 'Foxhound applies to strong fits and checks with you when it\'s a close call.'
              : 'Foxhound applies more broadly. Use this if you want maximum volume.'}
      </div>
    </div>
  );
}

function AutoCapability({ label, desc }: { label: string; desc: string }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--vl)', display: 'inline-block', marginTop: 7, flexShrink: 0 }} />
      <div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 12, color: 'var(--t3)', lineHeight: 1.6, marginTop: 2 }}>{desc}</div>
      </div>
    </div>
  );
}

function matchDescriptor(score: number): string {
  if (score >= 90) return 'Exact - near-perfect matches only';
  if (score >= 80) return 'Strong - high-confidence matches';
  if (score >= 70) return 'Balanced - quality with steady volume';
  if (score >= 60) return 'Broad - more volume, less precision';
  return 'Very broad - expect lower fit quality';
}

function clampThreshold(value: number): number {
  if (Number.isNaN(value)) return 75;
  return Math.min(100, Math.max(50, value));
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
  const thresholdValue = clampThreshold(parseInt(threshold, 10));

  // Notifications (from settings)
  const [notifyApply, setNotifyApply] = useState(true);
  const [notifyDigest, setNotifyDigest] = useState(true);
  const [notifyChannels, setNotifyChannels] = useState<string[]>(['email']);

  // Blocklist (from settings)
  const [blocklist, setBlocklist] = useState('');

  // Application profile (from profile)
  const [visaStatus, setVisaStatus] = useState('');
  const [salaryExpectation, setSalaryExpectation] = useState('');
  const [noticePeriod, setNoticePeriod] = useState('');
  const [workPreference, setWorkPreference] = useState('');
  const [willingToRelocate, setWillingToRelocate] = useState(false);
  const [gender, setGender] = useState('');
  const [race, setRace] = useState('');
  const [hispanicLatino, setHispanicLatino] = useState('');
  const [veteranStatus, setVeteranStatus] = useState('');
  const [disabilityStatus, setDisabilityStatus] = useState('');
  const [howDidYouHear, setHowDidYouHear] = useState('');
  const [resumeFilename, setResumeFilename] = useState<string | null>(null);

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
          setVisaStatus((p.visa_status as string) || '');
          setSalaryExpectation((p.salary_expectation as string) || '');
          setNoticePeriod((p.notice_period as string) || '');
          setWorkPreference((p.work_preference as string) || '');
          setWillingToRelocate(Boolean(p.willing_to_relocate));
          setGender((p.gender as string) || '');
          setRace((p.race as string) || '');
          setHispanicLatino(p.hispanic_latino === true ? 'yes' : p.hispanic_latino === false ? 'no' : '');
          setVeteranStatus((p.veteran_status as string) || '');
          setDisabilityStatus((p.disability_status as string) || '');
          setHowDidYouHear((p.how_did_you_hear as string) || '');
          setResumeFilename((p.resume_filename as string | null) || null);
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
          setNotifyChannels(channels.length > 0 ? channels : ['email']);

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
    const nextChannels = (overrides.channels as string[] | undefined) ?? notifyChannels;
    debouncedSave(() => updateNotifications( {
      channels: nextChannels.length > 0 ? nextChannels : ['email'],
      on_apply: (overrides.on_apply as boolean | undefined) ?? notifyApply,
      daily_digest: (overrides.daily_digest as boolean | undefined) ?? notifyDigest,
    }));
  }

  function toggleNotifyChannel(channel: string) {
    const currentlySelected = notifyChannels.includes(channel);
    const next = currentlySelected
      ? notifyChannels.filter((c) => c !== channel)
      : [...notifyChannels, channel];
    const normalized = next.length > 0 ? next : ['email'];
    setNotifyChannels(normalized);
    saveNotifications({ channels: normalized });
  }

  function saveBlocklist(value?: string) {
    const list = (value ?? blocklist).split(',').map(s => s.trim()).filter(Boolean);
    debouncedSave(() => updateBlocklist( { blacklist: list }));
  }

  function saveApplicationProfile(overrides: Record<string, unknown> = {}) {
    const payload: Record<string, unknown> = {};
    const vs = (overrides.visa_status as string | undefined) ?? visaStatus;
    const se = (overrides.salary_expectation as string | undefined) ?? salaryExpectation;
    const np = (overrides.notice_period as string | undefined) ?? noticePeriod;
    const wp = (overrides.work_preference as string | undefined) ?? workPreference;
    const wr = (overrides.willing_to_relocate as boolean | undefined) ?? willingToRelocate;
    const gn = (overrides.gender as string | undefined) ?? gender;
    const rc = (overrides.race as string | undefined) ?? race;
    const hl = (overrides.hispanic_latino as string | undefined) ?? hispanicLatino;

    if (vs) payload.visa_status = vs;
    if (se) payload.salary_expectation = se;
    if (np) payload.notice_period = np;
    if (wp) payload.work_preference = wp;
    payload.willing_to_relocate = wr;
    if (gn) payload.gender = gn;
    if (rc) payload.race = rc;
    if (hl) payload.hispanic_latino = hl === 'yes' ? true : hl === 'no' ? false : null;
    const vs2 = (overrides.veteran_status as string | undefined) ?? veteranStatus;
    const ds = (overrides.disability_status as string | undefined) ?? disabilityStatus;
    const hdyh = (overrides.how_did_you_hear as string | undefined) ?? howDidYouHear;
    if (vs2) payload.veteran_status = vs2;
    if (ds) payload.disability_status = ds;
    if (hdyh) payload.how_did_you_hear = hdyh;

    debouncedSave(() => updateProfile(payload));
  }

  if (loading) {
    return (
      <AuthGuard>
        <AppNav />
        <PageSkeleton variant="settings" />
      </AuthGuard>
    );
  }

  return (
    <AuthGuard>
      <AppNav />
      <main style={{ paddingTop: 80, maxWidth: 1080, margin: '0 auto', padding: '80px 20px 140px', position: 'relative', zIndex: 1 }}>
        <ScrollReveal>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div className="section-label">Settings</div>
              <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', textTransform: 'uppercase' }}>
                YOUR PREFERENCES
              </h1>
            </div>
            {(saving || saveMsg) && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: saving ? 'var(--t3)' : saveMsg === 'Saved' ? 'var(--g)' : 'var(--error, #f87171)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                {saving ? 'Saving...' : saveMsg}
              </div>
            )}
          </div>
        </ScrollReveal>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(440px, 1fr))', gap: 24, marginTop: 8 }}>
        {/* Job Preferences */}
        <ScrollReveal delay={1}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', height: '100%', boxSizing: 'border-box' as const }}>
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
              Changes save automatically and update your job matches.
            </div>
          </div>
        </ScrollReveal>

        {/* Application Profile */}
        <ScrollReveal delay={2}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', height: '100%', boxSizing: 'border-box' as const }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              02 / Application Profile
            </div>
            <div style={{ fontSize: 13, color: 'var(--t3)', padding: '12px 0', borderBottom: '1px solid var(--b)', lineHeight: 1.6 }}>
              Set these once and Foxhound fills them in on every application.
            </div>

            <SettingSelect
              label="Gender"
              value={gender}
              onChange={(v) => { setGender(v); saveApplicationProfile({ gender: v }); }}
              options={[
                { value: 'male', label: 'Male' },
                { value: 'female', label: 'Female' },
                { value: 'non_binary', label: 'Non-binary' },
                { value: 'decline', label: 'Decline to self identify' },
              ]}
            />

            <SettingSelect
              label="Race / Ethnicity"
              value={race}
              onChange={(v) => { setRace(v); saveApplicationProfile({ race: v }); }}
              options={[
                { value: 'white', label: 'White' },
                { value: 'black', label: 'Black or African American' },
                { value: 'asian', label: 'Asian' },
                { value: 'native', label: 'American Indian or Alaska Native' },
                { value: 'pacific', label: 'Native Hawaiian or Pacific Islander' },
                { value: 'two_or_more', label: 'Two or More Races' },
                { value: 'decline', label: 'Decline to self identify' },
              ]}
            />

            <SettingSelect
              label="Hispanic or Latino?"
              value={hispanicLatino}
              onChange={(v) => { setHispanicLatino(v); saveApplicationProfile({ hispanic_latino: v }); }}
              options={[
                { value: 'yes', label: 'Yes' },
                { value: 'no', label: 'No' },
                { value: '', label: 'Decline to self identify' },
              ]}
            />

            <SettingSelect
              label="Visa status"
              value={visaStatus}
              onChange={(v) => { setVisaStatus(v); saveApplicationProfile({ visa_status: v }); }}
              options={[
                { value: 'citizen', label: 'US Citizen' },
                { value: 'green_card', label: 'Green Card' },
                { value: 'h1b', label: 'H-1B Visa' },
                { value: 'opt', label: 'OPT' },
                { value: 'need_sponsorship', label: 'Need Sponsorship' },
              ]}
            />

            <SettingInput
              label="Salary expectation"
              placeholder="$150,000 base"
              value={salaryExpectation}
              onChange={(v) => { setSalaryExpectation(v); saveApplicationProfile({ salary_expectation: v }); }}
            />

            <SettingInput
              label="Notice period"
              placeholder="2 weeks, Immediately..."
              value={noticePeriod}
              onChange={(v) => { setNoticePeriod(v); saveApplicationProfile({ notice_period: v }); }}
            />

            <SettingSelect
              label="Work preference"
              value={workPreference}
              onChange={(v) => { setWorkPreference(v); saveApplicationProfile({ work_preference: v }); }}
              options={[
                { value: 'remote', label: 'Remote' },
                { value: 'hybrid', label: 'Hybrid' },
                { value: 'office', label: 'In-Office' },
              ]}
            />

            <SettingSelect
              label="Veteran status"
              value={veteranStatus}
              onChange={(v) => { setVeteranStatus(v); saveApplicationProfile({ veteran_status: v }); }}
              options={[
                { value: 'not_veteran', label: 'I am not a protected veteran' },
                { value: 'veteran', label: 'I am a protected veteran' },
                { value: 'decline', label: 'Decline to self identify' },
              ]}
            />

            <SettingSelect
              label="Disability status"
              value={disabilityStatus}
              onChange={(v) => { setDisabilityStatus(v); saveApplicationProfile({ disability_status: v }); }}
              options={[
                { value: 'no', label: 'No, I do not have a disability' },
                { value: 'yes', label: 'Yes, I have a disability' },
                { value: 'decline', label: 'Decline to self identify' },
              ]}
            />

            <SettingSelect
              label="How did you hear about us?"
              value={howDidYouHear}
              onChange={(v) => { setHowDidYouHear(v); saveApplicationProfile({ how_did_you_hear: v }); }}
              options={[
                { value: 'linkedin', label: 'LinkedIn' },
                { value: 'job_board', label: 'Job Board' },
                { value: 'referral', label: 'Referral' },
                { value: 'company_website', label: 'Company Website' },
                { value: 'social_media', label: 'Social Media' },
                { value: 'other', label: 'Other' },
              ]}
            />

            <Toggle
              label="Willing to relocate"
              desc="Open to relocating for the right opportunity"
              enabled={willingToRelocate}
              onChange={() => { const next = !willingToRelocate; setWillingToRelocate(next); saveApplicationProfile({ willing_to_relocate: next }); }}
            />

            <div style={{ padding: '12px 0', fontSize: 12, color: 'var(--t3)' }}>
              Foxhound uses these to fill in common application questions.
            </div>
          </div>
        </ScrollReveal>

        {/* Autopilot */}
        <ScrollReveal delay={3}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', height: '100%', boxSizing: 'border-box' as const }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              03 / Autopilot
            </div>
            <div style={{ fontSize: 13, color: 'var(--t3)', padding: '12px 0', borderBottom: '1px solid var(--b)', lineHeight: 1.6 }}>
              Control how much Foxhound does on its own.
            </div>
            <Toggle
              label="Autopilot mode"
              desc="Let Foxhound apply to strong matches automatically"
              enabled={autopilot}
              onChange={() => { const next = !autopilot; setAutopilot(next); saveAutopilot({ enabled: next }); }}
            />
            <AutonomyMeter enabled={autopilot} threshold={thresholdValue} />
            <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 12 }}>
                Minimum fit score ({thresholdValue}%)
              </label>
              <input
                type="range"
                min={50}
                max={100}
                value={thresholdValue}
                onChange={(e) => {
                  const next = String(clampThreshold(parseInt(e.target.value, 10)));
                  setThreshold(next);
                  saveAutopilot({ threshold: next });
                }}
                style={{ width: '100%', accentColor: 'var(--v)' }}
              />
              <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 10 }}>
                {matchDescriptor(thresholdValue)}
              </div>
            </div>
            <SettingInput label="Max applications per day" placeholder="10" value={dailyLimit} onChange={(v) => { setDailyLimit(v); saveAutopilot({ daily_limit: v }); }} />
            {!resumeFilename && (
              <div style={{
                marginTop: 12,
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid rgba(251,191,36,0.2)',
                background: 'rgba(251,191,36,0.06)',
                fontSize: 12,
                color: 'var(--t2)',
                lineHeight: 1.6,
              }}>
                Foxhound can keep searching without a resume, but it cannot submit applications until you upload one.
                {' '}
                <Link href="/onboard" style={{ color: 'var(--vl)', textDecoration: 'none' }}>
                  Upload resume
                </Link>
                {' '}
                to unlock autopilot apply.
              </div>
            )}
            <div style={{ padding: '16px 0 4px' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>
                What Foxhound does for you
              </div>
              <div style={{ display: 'grid', gap: 10 }}>
                <AutoCapability label="People research after apply" desc="Find the hiring manager and people to reach out to." />
                <AutoCapability label="Company brief assembly" desc="Pull together the key facts about a company before you follow up." />
                <AutoCapability label="Status tracking and ghost checks" desc="Watch if the job posting changes after you apply." />
                <AutoCapability label="Morning briefing and alerts" desc="Sum up what happened overnight and flag anything that needs you." />
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* Notifications */}
        <ScrollReveal delay={3}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', height: '100%', boxSizing: 'border-box' as const }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              04 / Notifications
            </div>
            <Toggle
              label="Application confirmations"
              desc="Get notified every time Foxhound applies for you"
              enabled={notifyApply}
              onChange={() => { const next = !notifyApply; setNotifyApply(next); saveNotifications({ on_apply: next }); }}
            />
            <Toggle
              label="Daily digest"
              desc="End-of-day summary of what Foxhound did and new matches"
              enabled={notifyDigest}
              onChange={() => { const next = !notifyDigest; setNotifyDigest(next); saveNotifications({ daily_digest: next }); }}
            />
            <div style={{ padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 10 }}>
                How to reach you
              </label>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {['slack', 'discord', 'sms', 'email'].map((ch) => (
                  <button
                    key={ch}
                    onClick={() => toggleNotifyChannel(ch)}
                    style={{
                      fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
                      padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
                      border: `1px solid ${notifyChannels.includes(ch) ? 'var(--bv)' : 'var(--b)'}`,
                      background: notifyChannels.includes(ch) ? 'var(--vf)' : 'transparent',
                      color: notifyChannels.includes(ch) ? 'var(--vl)' : 'var(--t3)',
                      transition: 'all 0.2s',
                    }}
                  >
                    {ch}
                  </button>
                ))}
              </div>
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--t3)', lineHeight: 1.6 }}>
                Slack and Discord notifications are reply-aware. You can answer pending questions and steer Foxhound directly from those channels.
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* Blocklist */}
        <ScrollReveal delay={4}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', height: '100%', boxSizing: 'border-box' as const }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              05 / Blocklist
            </div>
            <SettingInput
              label="Companies to avoid"
              placeholder="Company A, Company B..."
              value={blocklist}
              onChange={(v) => { setBlocklist(v); saveBlocklist(v); }}
            />
            <div style={{ fontSize: 12, color: 'var(--t3)', padding: '12px 0' }}>
              Foxhound will never apply to these companies, even on autopilot.
            </div>
          </div>
        </ScrollReveal>

        {/* Account */}
        <ScrollReveal delay={5}>
          <div style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, padding: '8px 24px', height: '100%', boxSizing: 'border-box' as const }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '16px 0', borderBottom: '1px solid var(--b)' }}>
              06 / Account
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
                border: '1px solid rgba(239,68,68,0.15)', borderRadius: 6, padding: '8px 16px', cursor: 'pointer',
                letterSpacing: '0.04em', textTransform: 'uppercase',
              }}>
                Delete account
              </button>
            </div>
          </div>
        </ScrollReveal>
        </div>{/* close 2-column grid */}
      </main>
    </AuthGuard>
  );
}
