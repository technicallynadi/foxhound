'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import ScrollReveal from '@/components/landing/ScrollReveal';
import AppNav from '@/components/AppNav';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';
const PER_PAGE = 50;

interface Job {
  id?: string;
  title: string;
  company: string;
  location: string;
  remote_type: string | null;
  ats_type: string | null;
  source?: string;
  apply_url?: string;
  salary_min?: number | null;
  salary_max?: number | null;
  posted_at?: string;
  match_score?: number;
  custom_questions_json?: string | null;
}

function JobCard({ job, onClick }: { job: Job; onClick: () => void }) {
  const remote = job.remote_type === 'remote';
  const source = job.ats_type || job.source || 'unknown';

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }}
      aria-label={`${job.title} at ${job.company}`}
      style={{
        background: 'var(--bg)', padding: 26, position: 'relative', cursor: 'pointer',
        transition: 'background 0.3s, outline 0.15s', minHeight: 160, display: 'flex', flexDirection: 'column',
        minWidth: 0, overflow: 'hidden', outline: 'none',
      }}
      onFocus={(e) => {
        e.currentTarget.style.outline = '2px solid var(--v)';
        e.currentTarget.style.outlineOffset = '-2px';
      }}
      onBlur={(e) => {
        e.currentTarget.style.outline = 'none';
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--sf)';
        const accent = e.currentTarget.querySelector('.job-accent') as HTMLElement;
        if (accent) accent.style.opacity = '1';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'var(--bg)';
        const accent = e.currentTarget.querySelector('.job-accent') as HTMLElement;
        if (accent) accent.style.opacity = '0';
      }}
    >
      <div className="job-accent" style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 2,
        background: 'var(--v)', opacity: 0, transition: 'opacity 0.3s',
      }} />

      <div className="job-card-source">
        {source}{job.location ? ` · ${job.location}` : ''}
      </div>
      <div className="job-card-title">
        {job.title}
      </div>
      <div className="job-card-company">
        {job.company}
      </div>

      {/* Location + salary row */}
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
        marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--b)',
        display: 'flex', gap: 8, alignItems: 'center',
      }}>
        {remote && <span style={{ color: 'var(--g)' }}>Remote</span>}
        {!remote && job.location && <span>{job.location}</span>}
        {job.salary_min && job.salary_max && (
          <span>${(job.salary_min / 1000).toFixed(0)}k–${(job.salary_max / 1000).toFixed(0)}k</span>
        )}
      </div>

      {/* Form intelligence — only show if we have real scan data */}
      {job.custom_questions_json && (
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--vl)',
          marginTop: 8,
        }}>
          {(() => {
            try {
              const qs = JSON.parse(job.custom_questions_json);
              return `${qs.field_count || '?'} fields · ${qs.question_count || '?'} custom Qs · ~${qs.estimated_time || '?'} min`;
            } catch { return null; }
          })()}
        </div>
      )}

      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
        marginTop: 'auto', paddingTop: 10, display: 'inline-flex', alignItems: 'center', gap: 4,
        textTransform: 'uppercase', letterSpacing: '0.04em',
      }}>
        See match % ↗
      </div>
    </div>
  );
}

function JobDetailModal({ job, onClose }: { job: Job; onClose: () => void }) {
  const router = useRouter();

  function handleApplyWithFoxhound() {
    router.push('/login');
  }
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 200,
        background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 16,
          maxWidth: 600, width: '100%', maxHeight: '85vh', overflow: 'auto',
          padding: '24px 20px', animation: 'panel-open 200ms ease-out',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
              {job.ats_type || job.source} · {job.location || 'Not specified'}
            </div>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>
              {job.title}
            </h2>
            <div style={{ fontSize: 16, color: 'var(--t2)', marginTop: 4 }}>{job.company}</div>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 32, height: 32, borderRadius: 8, border: 'none',
              background: 'rgba(255,255,255,0.04)', color: 'var(--t3)',
              cursor: 'pointer', fontSize: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            &times;
          </button>
        </div>

        {/* Apply link */}
        {job.apply_url && (
          <a
            href={job.apply_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t2)',
              marginTop: 16, textDecoration: 'underline', textUnderlineOffset: 3,
            }}
          >
            Apply on {job.company}&apos;s site →
          </a>
        )}

        {/* Divider */}
        <div style={{ width: '100%', height: 1, background: 'var(--b)', margin: '24px 0' }} />

        {/* CTA — Beta waitlist */}
        <div style={{ marginTop: 24, textAlign: 'center' }}>
          <button onClick={handleApplyWithFoxhound} className="btn-solid" style={{ cursor: 'pointer' }}>
            Apply with Foxhound →
          </button>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', marginTop: 10, letterSpacing: '0.04em' }}>
            Coming soon — join the beta to get early access
          </p>
        </div>
      </div>

      <style jsx>{`
        @keyframes panel-open {
          from { opacity: 0; transform: scale(0.95) translateY(8px); }
          to { opacity: 1; transform: scale(1) translateY(0); }
        }
      `}</style>
    </div>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);
  const [totalJobs, setTotalJobs] = useState(0);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [search, setSearch] = useState('');
  const pageRef = useRef(1);
  const hasMoreRef = useRef(true);
  const [filter, setFilter] = useState('all');
  const [locationFilter, setLocationFilter] = useState('all');
  const sentinel = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);

  const fetchJobs = useCallback(async (pageNum: number) => {
    if (loadingRef.current || !hasMoreRef.current) return;
    loadingRef.current = true;
    try {
      const res = await fetch(`${API_BASE}/api/v1/jobs/public?page=${pageNum}&per_page=${PER_PAGE}`);
      if (!res.ok) return;
      const data = await res.json();
      const newJobs = data.jobs || [];
      if (data.total) setTotalJobs(data.total);
      const more = newJobs.length === PER_PAGE;
      setHasMore(more);
      hasMoreRef.current = more;
      pageRef.current = pageNum;
      setJobs((prev) => pageNum === 1 ? newJobs : [...prev, ...newJobs]);
    } catch { /* silent */ }
    finally { setLoading(false); loadingRef.current = false; }
  }, []);

  useEffect(() => { fetchJobs(1); }, [fetchJobs]);

  // Infinite scroll — uses refs to avoid stale closure
  useEffect(() => {
    function onScroll() {
      if (loadingRef.current || !hasMoreRef.current) return;
      const scrollBottom = window.innerHeight + window.scrollY;
      const docHeight = document.documentElement.scrollHeight;
      if (scrollBottom >= docHeight - 1500) {
        fetchJobs(pageRef.current + 1);
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [fetchJobs]);

  // Region matchers — real location data looks like "Starbase, TX", "São Paulo, São Paulo, Brazil", "Remote - United Kingdom"
  const US_STATES = [
    'al','ak','az','ar','ca','co','ct','de','fl','ga','hi','id','il','in','ia',
    'ks','ky','la','me','md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj',
    'nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt',
    'va','wa','wv','wi','wy','dc',
  ];
  const REGION_KEYWORDS: Record<string, string[]> = {
    us: ['united states', ', usa'],
    europe: [
      'united kingdom', 'uk', 'london', 'england', 'scotland',
      'germany', 'berlin', 'munich', 'frankfurt', 'hamburg',
      'france', 'paris', 'lyon',
      'netherlands', 'amsterdam', 'rotterdam',
      'ireland', 'dublin',
      'spain', 'madrid', 'barcelona',
      'italy', 'milan', 'rome',
      'sweden', 'stockholm',
      'denmark', 'copenhagen',
      'norway', 'oslo',
      'finland', 'helsinki',
      'switzerland', 'zurich', 'geneva',
      'austria', 'vienna',
      'poland', 'warsaw', 'krakow',
      'portugal', 'lisbon',
      'belgium', 'brussels',
      'czech', 'prague',
      'romania', 'bucharest',
    ],
    canada: [
      'canada', 'toronto', 'vancouver', 'montreal', 'ottawa', 'calgary', 'edmonton',
      ', on', ', bc', ', qc', ', ab', ', mb', ', sk', ', ns', ', nb',
    ],
    india: ['india', 'bangalore', 'bengaluru', 'mumbai', 'hyderabad', 'delhi', 'pune', 'chennai', 'gurugram', 'noida', 'gurgaon'],
    latam: ['brazil', 'mexico', 'argentina', 'colombia', 'chile', 'são paulo', 'sao paulo', 'mexico city', 'buenos aires', 'bogota'],
    apac: ['australia', 'sydney', 'melbourne', 'singapore', 'japan', 'tokyo', 'south korea', 'seoul', 'hong kong', 'taiwan', 'new zealand', 'auckland'],
    israel: ['israel', 'tel aviv', 'jerusalem', 'haifa'],
  };

  function matchesRegion(loc: string, region: string): boolean {
    const l = loc.toLowerCase().trim();
    if (region === 'us') {
      // Check if location ends with a US state abbreviation (e.g. "Starbase, TX")
      const endsWithState = US_STATES.some((st) => l.endsWith(`, ${st}`));
      if (endsWithState) return true;
      // Also check keyword matches like "United States"
      return REGION_KEYWORDS.us.some((k) => l.includes(k));
    }
    const keywords = REGION_KEYWORDS[region];
    if (!keywords) return l.includes(region.toLowerCase());
    return keywords.some((k) => l.includes(k));
  }

  const filtered = jobs.filter((j) => {
    if (search) {
      const q = search.toLowerCase();
      const matchesTitle = j.title.toLowerCase().includes(q);
      const matchesCompany = j.company.toLowerCase().includes(q);
      const matchesLocation = (j.location || '').toLowerCase().includes(q);
      if (!matchesTitle && !matchesCompany && !matchesLocation) return false;
    }
    if (filter === 'remote' && j.remote_type !== 'remote') return false;
    if (locationFilter !== 'all') {
      if (!matchesRegion(j.location || '', locationFilter)) return false;
    }
    return true;
  });

  return (
    <>
      <AppNav />

      <main style={{ paddingTop: 80, position: 'relative', zIndex: 1 }}>
        {/* Header */}
        <section style={{ padding: '100px 20px 0', maxWidth: 1200, margin: '0 auto' }}>
          <ScrollReveal>
            <div className="section-label">Jobs</div>
          </ScrollReveal>
          <ScrollReveal delay={1}>
            <div className="section-heading">
              OPEN ROLES. <span className="dim">FOXHOUND HANDLES THE REST.</span>
            </div>
          </ScrollReveal>
          <ScrollReveal delay={2}>
            <p style={{ color: 'var(--t2)', marginTop: 12, fontSize: 15, maxWidth: 480 }}>
              Browse thousands of open roles across companies and industries. Found one you like? Foxhound fills out the form and applies for you.
            </p>
          </ScrollReveal>

          {/* Search + Filters */}
          <ScrollReveal delay={3}>
            <div style={{ marginTop: 32, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Search bar */}
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by title or company..."
                className="input"
                style={{ width: '100%', padding: '12px 16px', fontSize: 14 }}
              />

              {/* Filter row */}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                {[
                  { key: 'all', label: 'All' },
                  { key: 'remote', label: 'Remote' },
                ].map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    style={{
                      fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.06em',
                      textTransform: 'uppercase', padding: '8px 20px',
                      border: `1px solid ${filter === f.key ? 'var(--bv)' : 'var(--b)'}`,
                      borderRadius: 6, background: filter === f.key ? 'var(--vf)' : 'transparent',
                      color: filter === f.key ? 'var(--vl)' : 'var(--t3)',
                      cursor: 'pointer', transition: 'all 0.2s',
                    }}
                  >
                    {f.label}
                  </button>
                ))}

                {/* Location dropdown */}
                <select
                  value={locationFilter}
                  onChange={(e) => setLocationFilter(e.target.value)}
                  className="input"
                  style={{
                    padding: '8px 12px', fontSize: 11, fontFamily: 'var(--font-mono)',
                    letterSpacing: '0.06em', textTransform: 'uppercase',
                    borderRadius: 6, cursor: 'pointer', minWidth: 140,
                  }}
                >
                  <option value="all">All locations</option>
                  <option value="us">United States</option>
                  <option value="canada">Canada</option>
                  <option value="europe">Europe / UK</option>
                  <option value="india">India</option>
                  <option value="israel">Israel</option>
                  <option value="latam">Latin America</option>
                  <option value="apac">Asia Pacific</option>
                </select>

                {/* Result count */}
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)', letterSpacing: '0.04em', marginLeft: 'auto' }}>
                  {totalJobs > 0 ? totalJobs.toLocaleString() : filtered.length} roles
                </span>
              </div>
            </div>
          </ScrollReveal>
        </section>

        {/* Job grid */}
        <section style={{ padding: '32px 20px 140px', maxWidth: 1200, margin: '0 auto' }}>
          {loading && jobs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 80, color: 'var(--t3)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              Loading jobs...
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 80, color: 'var(--t3)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              No jobs found
            </div>
          ) : (
            <div className="jobs-grid" style={{
              display: 'grid', gap: 1,
              background: 'var(--b)', border: '1px solid var(--b)',
            }}>
              {filtered.map((job, i) => (
                <JobCard key={job.id || `${job.company}-${job.title}-${i}`} job={job} onClick={() => setSelectedJob(job)} />
              ))}
            </div>
          )}

          {/* Infinite scroll sentinel */}
          {hasMore && <div ref={sentinel} style={{ height: 1 }} />}

          {loadingRef.current && jobs.length > 0 && (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--t3)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              Loading more...
            </div>
          )}
        </section>
      </main>

      {/* Job detail modal */}
      {selectedJob && (
        <JobDetailModal job={selectedJob} onClose={() => setSelectedJob(null)} />
      )}
    </>
  );
}
