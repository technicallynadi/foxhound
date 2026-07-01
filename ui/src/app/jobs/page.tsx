"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ScrollReveal from "@/components/landing/ScrollReveal";
import AppNav from "@/components/AppNav";
import PageSkeleton from "@/components/PageSkeleton";
import ReconCard from "@/components/ReconCard";
import { useAuth } from "@/lib/auth-context";
import { useAgent } from "@/components/agent/AgentProvider";
import { getProfile } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
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
  ghost_score?: number | null;
  ghost_risk?: "verified" | "caution" | "ghost_risk" | null;
  ghost_factors_json?: string | null;
}

const GHOST_CONFIG: Record<
  string,
  { color: string; label: string; dotShadow: string }
> = {
  verified: {
    color: "var(--g)",
    label: "Verified",
    dotShadow: "0 0 4px var(--g)",
  },
  caution: {
    color: "var(--warning)",
    label: "Caution",
    dotShadow: "0 0 4px var(--warning)",
  },
  ghost_risk: {
    color: "var(--error)",
    label: "Ghost Risk",
    dotShadow: "0 0 4px var(--error)",
  },
};

const GHOST_DEFAULT = {
  color: "var(--t3)",
  label: "Unverified",
  dotShadow: "none",
};

function GhostBadge({ job }: { job: Job }) {
  const [showTip, setShowTip] = useState(false);

  // Don't show badge if no ghost data yet
  if (!job.ghost_risk) return null;

  const cfg = GHOST_CONFIG[job.ghost_risk] ?? GHOST_DEFAULT;

  let factors: string[] = [];
  if (job.ghost_factors_json) {
    try {
      const parsed = JSON.parse(job.ghost_factors_json);
      factors = Array.isArray(parsed) ? parsed : [];
    } catch {
      /* ignore malformed */
    }
  }

  return (
    <span
      onMouseEnter={() => setShowTip(true)}
      onMouseLeave={() => setShowTip(false)}
      style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 4 }}
    >
      {/* Dot */}
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: "50%",
          background: cfg.color,
          boxShadow: cfg.dotShadow,
          flexShrink: 0,
        }}
      />
      {/* Label */}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          color: cfg.color,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          lineHeight: 1,
        }}
      >
        {cfg.label}
      </span>

      {/* Tooltip */}
      {showTip && factors.length > 0 && (
        <span
          role="tooltip"
          style={{
            position: "absolute",
            bottom: "calc(100% + 8px)",
            left: 0,
            background: "#111",
            border: "1px solid var(--b)",
            borderRadius: 6,
            padding: "8px 10px",
            width: 200,
            zIndex: 50,
            pointerEvents: "none",
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              color: "var(--t3)",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              display: "block",
              marginBottom: 6,
            }}
          >
            Why this is flagged
          </span>
          {factors.map((f, i) => (
            <span
              key={i}
              style={{
                display: "block",
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                color: "var(--t2)",
                lineHeight: 1.6,
              }}
            >
              {f}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

function JobCard({
  job,
  onClick,
  onRecon,
  canUseQuickReport,
}: {
  job: Job;
  onClick: () => void;
  onRecon: () => void;
  canUseQuickReport: boolean;
}) {
  const remote = job.remote_type === "remote";
  const source = job.ats_type || job.source || "unknown";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      aria-label={`${job.title} at ${job.company}`}
      style={{
        background: "var(--bg)",
        padding: 26,
        position: "relative",
        cursor: "pointer",
        transition: "background 0.3s, outline 0.15s",
        minHeight: 160,
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
        overflow: "hidden",
        outline: "none",
      }}
      onFocus={(e) => {
        e.currentTarget.style.outline = "2px solid var(--v)";
        e.currentTarget.style.outlineOffset = "-2px";
      }}
      onBlur={(e) => {
        e.currentTarget.style.outline = "none";
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--sf)";
        const accent = e.currentTarget.querySelector(
          ".job-accent",
        ) as HTMLElement;
        if (accent) accent.style.opacity = "1";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "var(--bg)";
        const accent = e.currentTarget.querySelector(
          ".job-accent",
        ) as HTMLElement;
        if (accent) accent.style.opacity = "0";
      }}
    >
      <div
        className="job-accent"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 2,
          background: "var(--v)",
          opacity: 0,
          transition: "opacity 0.3s",
        }}
      />

      <div className="job-card-source" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {source}
        {job.location ? ` · ${job.location}` : ""}
      </div>
      <div className="job-card-title">{job.title}</div>
      <div
        className="job-card-company"
        style={{ display: "flex", alignItems: "center", gap: 8 }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {job.company}
        </span>
        <GhostBadge job={job} />
      </div>

      {/* Location + salary row */}
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--t3)",
          marginTop: 14,
          paddingTop: 14,
          borderTop: "1px solid var(--b)",
          display: "flex",
          gap: 8,
          alignItems: "center",
          overflow: "hidden",
        }}
      >
        {remote && <span style={{ color: "var(--g)", flexShrink: 0 }}>Remote</span>}
        {!remote && job.location && (
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {job.location}
          </span>
        )}
        {job.salary_min && job.salary_max && (
          <span>
            ${(job.salary_min / 1000).toFixed(0)}k–$
            {(job.salary_max / 1000).toFixed(0)}k
          </span>
        )}
      </div>

      {/* Form intelligence — only show if we have real scan data */}
      {job.custom_questions_json && (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--vl)",
            marginTop: 8,
          }}
        >
          {(() => {
            try {
              const qs = JSON.parse(job.custom_questions_json);
              return `${qs.field_count || "?"} fields · ${qs.question_count || "?"} custom Qs · ~${qs.estimated_time || "?"} min`;
            } catch {
              return null;
            }
          })()}
        </div>
      )}

      <div
        style={{
          marginTop: "auto",
          paddingTop: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--t3)",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {job.match_score ? `${job.match_score}% fit` : 'View details ↗'}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRecon();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.stopPropagation();
            }
          }}
          aria-label={
            canUseQuickReport
              ? `Quick company brief for ${job.company}`
              : `Sign in to open quick company brief for ${job.company}`
          }
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            fontWeight: 500,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--vl)",
            background: "transparent",
            border: "1px solid var(--b)",
            borderRadius: 4,
            padding: "5px 10px",
            cursor: "pointer",
            transition: "border-color 0.2s, background 0.2s",
            whiteSpace: "nowrap",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "var(--bv)";
            e.currentTarget.style.background = "var(--vf)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "var(--b)";
            e.currentTarget.style.background = "transparent";
          }}
        >
          {canUseQuickReport ? "COMPANY INFO" : "SIGN IN FOR INFO"}
        </button>
      </div>
    </div>
  );
}

function JobDetailModal({ job, onClose, canApplyWithFoxhound }: { job: Job; onClose: () => void; canApplyWithFoxhound: boolean }) {
  const router = useRouter();
  const { user } = useAuth();
  const { send, open } = useAgent();

  function handleApplyWithFoxhound() {
    if (!user) {
      router.push("/login");
      return;
    }
    if (!canApplyWithFoxhound) {
      router.push('/onboard');
      return;
    }
    // Logged in — open agent and trigger apply
    open();
    onClose();
    setTimeout(() => {
      send(`Apply to ${job.company} — ${job.title}`);
    }, 300);
  }
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "rgba(0,0,0,0.7)",
        backdropFilter: "blur(8px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--sf)",
          border: "1px solid var(--b)",
          borderRadius: 12,
          maxWidth: 600,
          width: "100%",
          maxHeight: "85vh",
          overflow: "auto",
          padding: "24px 20px",
          animation: "panel-open 200ms ease-out",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "start",
          }}
        >
          <div>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--t3)",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                marginBottom: 8,
              }}
            >
              {job.ats_type || job.source} · {job.location || "Not specified"}
            </div>
            <h2
              style={{
                fontFamily: "var(--font-display)",
                fontSize: 24,
                fontWeight: 700,
                letterSpacing: "-0.02em",
              }}
            >
              {job.title}
            </h2>
            <div style={{ fontSize: 16, color: "var(--t2)", marginTop: 4 }}>
              {job.company}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              border: "none",
              background: "rgba(255,255,255,0.04)",
              color: "var(--t3)",
              cursor: "pointer",
              fontSize: 16,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
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
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--t2)",
              marginTop: 16,
              textDecoration: "underline",
              textUnderlineOffset: 3,
            }}
          >
            Apply on {job.company}&apos;s site →
          </a>
        )}

        {/* Divider */}
        <div
          style={{
            width: "100%",
            height: 1,
            background: "var(--b)",
            margin: "24px 0",
          }}
        />

        {/* CTA — Early access waitlist */}
        <div style={{ marginTop: 24, textAlign: "center" }}>
          <button
            onClick={handleApplyWithFoxhound}
            className="btn-solid"
            style={{ cursor: "pointer", opacity: user && !canApplyWithFoxhound ? 0.72 : 1 }}
          >
            {user && !canApplyWithFoxhound ? 'Add Resume To Apply →' : 'Apply with Foxhound →'}
          </button>
          <p
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--t3)",
              marginTop: 10,
              letterSpacing: "0.04em",
            }}
          >
            {user
              ? canApplyWithFoxhound
                ? (job.ats_type === "greenhouse" || job.ats_type === "lever" || job.ats_type === "ashby")
                  ? "One click — Foxhound handles the form"
                  : "Foxhound will fill out and submit this application"
                : "Add your resume so Foxhound can apply for you."
              : "Browse every role freely — sign in when you want to apply"}
          </p>
        </div>
      </div>

      <style jsx>{`
        @keyframes panel-open {
          from {
            opacity: 0;
            transform: scale(0.95) translateY(8px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
      `}</style>
    </div>
  );
}

export default function JobsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const userId = user?.id || null;
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);
  const [totalJobs, setTotalJobs] = useState(0);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [reconJob, setReconJob] = useState<Job | null>(null);
  const [search, setSearch] = useState("");
  const [canApplyWithFoxhound, setCanApplyWithFoxhound] = useState(false);
  const pageRef = useRef(1);

  useEffect(() => {
    if (!userId) return;
    getProfile()
      .then((profile) => setCanApplyWithFoxhound(Boolean(profile.resume_filename)))
      .catch(() => setCanApplyWithFoxhound(false));
  }, [userId]);
  const hasMoreRef = useRef(true);
  const [filter, setFilter] = useState("all");
  const [locationFilter, setLocationFilter] = useState("all");
  const sentinel = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);

  const handleRecon = useCallback((job: Job) => {
    if (!user) {
      router.push("/login");
      return;
    }
    setReconJob(job);
  }, [router, user]);

  const fetchJobs = useCallback(async (pageNum: number) => {
    if (loadingRef.current || !hasMoreRef.current) return;
    loadingRef.current = true;
    try {
      let newJobs: Job[] = [];
      let total = 0;

      // Get auth token if available — backend returns match scores when authenticated
      const { getAccessToken } = await import("@/lib/supabase");
      const token = await getAccessToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      // Try the configured backend first; fall back to the built-in Next.js
      // route (live Remotive feed) when the backend/database is unavailable.
      const query = `page=${pageNum}&per_page=${PER_PAGE}`;
      const sources = API_BASE
        ? [`${API_BASE}/api/v1/jobs/public?${query}`, `/api/v1/jobs/public?${query}`]
        : [`/api/v1/jobs/public?${query}`];
      for (const url of sources) {
        try {
          const res = await fetch(url, { headers });
          if (!res.ok) continue;
          const data = await res.json();
          const list: Job[] = data.jobs || [];
          newJobs = list;
          total = data.total || 0;
          if (list.length) break; // got results — stop; else try the fallback
        } catch {
          /* source unavailable — try the next one */
        }
      }

      if (total) setTotalJobs(total);
      const more = newJobs.length === PER_PAGE;
      setHasMore(more);
      hasMoreRef.current = more;
      pageRef.current = pageNum;
      setJobs((prev) => (pageNum === 1 ? newJobs : [...prev, ...newJobs]));
    } catch {
      /* silent */
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    fetchJobs(1);
  }, [fetchJobs]);

  // Infinite scroll — listen on body (html has overflow:hidden)
  useEffect(() => {
    const scrollEl = document.body;
    function onScroll() {
      if (loadingRef.current || !hasMoreRef.current) return;
      const scrollBottom = scrollEl.scrollTop + scrollEl.clientHeight;
      const scrollHeight = scrollEl.scrollHeight;
      if (scrollBottom >= scrollHeight - 2000) {
        fetchJobs(pageRef.current + 1);
      }
    }
    scrollEl.addEventListener("scroll", onScroll, { passive: true });
    return () => scrollEl.removeEventListener("scroll", onScroll);
  }, [fetchJobs]);

  // Region matchers — real location data looks like "Starbase, TX", "São Paulo, São Paulo, Brazil", "Remote - United Kingdom"
  const US_STATES = [
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
  ];
  const REGION_KEYWORDS: Record<string, string[]> = {
    us: ["united states", ", usa"],
    europe: [
      "united kingdom",
      "uk",
      "london",
      "england",
      "scotland",
      "germany",
      "berlin",
      "munich",
      "frankfurt",
      "hamburg",
      "france",
      "paris",
      "lyon",
      "netherlands",
      "amsterdam",
      "rotterdam",
      "ireland",
      "dublin",
      "spain",
      "madrid",
      "barcelona",
      "italy",
      "milan",
      "rome",
      "sweden",
      "stockholm",
      "denmark",
      "copenhagen",
      "norway",
      "oslo",
      "finland",
      "helsinki",
      "switzerland",
      "zurich",
      "geneva",
      "austria",
      "vienna",
      "poland",
      "warsaw",
      "krakow",
      "portugal",
      "lisbon",
      "belgium",
      "brussels",
      "czech",
      "prague",
      "romania",
      "bucharest",
    ],
    canada: [
      "canada",
      "toronto",
      "vancouver",
      "montreal",
      "ottawa",
      "calgary",
      "edmonton",
      ", on",
      ", bc",
      ", qc",
      ", ab",
      ", mb",
      ", sk",
      ", ns",
      ", nb",
    ],
    india: [
      "india",
      "bangalore",
      "bengaluru",
      "mumbai",
      "hyderabad",
      "delhi",
      "pune",
      "chennai",
      "gurugram",
      "noida",
      "gurgaon",
    ],
    latam: [
      "brazil",
      "mexico",
      "argentina",
      "colombia",
      "chile",
      "são paulo",
      "sao paulo",
      "mexico city",
      "buenos aires",
      "bogota",
    ],
    apac: [
      "australia",
      "sydney",
      "melbourne",
      "singapore",
      "japan",
      "tokyo",
      "south korea",
      "seoul",
      "hong kong",
      "taiwan",
      "new zealand",
      "auckland",
    ],
    israel: ["israel", "tel aviv", "jerusalem", "haifa"],
  };

  function matchesRegion(loc: string, region: string): boolean {
    const l = loc.toLowerCase().trim();
    if (region === "us") {
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
      const matchesLocation = (j.location || "").toLowerCase().includes(q);
      if (!matchesTitle && !matchesCompany && !matchesLocation) return false;
    }
    if (filter === "remote" && j.remote_type !== "remote") return false;
    if (locationFilter !== "all") {
      if (!matchesRegion(j.location || "", locationFilter)) return false;
    }
    return true;
  });

  return (
    <>
      <AppNav />

      <main style={{ paddingTop: 80, position: "relative", zIndex: 1 }}>
        {/* Header */}
        <section
          style={{ padding: "80px 20px 0", maxWidth: 1200, margin: "0 auto" }}
        >
          <ScrollReveal>
            <div className="section-label">Jobs</div>
          </ScrollReveal>
          <ScrollReveal delay={1}>
            <div className="section-heading">
              FIND YOUR NEXT ROLE.{" "}
              <span className="dim">FOXHOUND HANDLES THE REST.</span>
            </div>
          </ScrollReveal>
          <ScrollReveal delay={2}>
            <p
              style={{
                color: "var(--t2)",
                marginTop: 12,
                fontSize: 15,
                maxWidth: 480,
              }}
            >
              Browse open roles across companies and industries.
              See something you like? Foxhound fills out the application and submits it for
              you.
            </p>
          </ScrollReveal>

          {/* Search + Filters */}
          <ScrollReveal delay={3}>
            <div
              style={{
                marginTop: 32,
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              {/* Search bar */}
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by title or company..."
                className="input"
                style={{ width: "100%", padding: "12px 16px", fontSize: 14 }}
              />

              {/* Filter row */}
              <div
                style={{
                  display: "flex",
                  gap: 8,
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                {[
                  { key: "all", label: "All" },
                  { key: "remote", label: "Remote" },
                ].map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      padding: "8px 20px",
                      border: `1px solid ${filter === f.key ? "var(--bv)" : "var(--b)"}`,
                      borderRadius: 6,
                      background:
                        filter === f.key ? "var(--vf)" : "transparent",
                      color: filter === f.key ? "var(--vl)" : "var(--t3)",
                      cursor: "pointer",
                      transition: "all 0.2s",
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
                    padding: "8px 12px",
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    borderRadius: 6,
                    cursor: "pointer",
                    minWidth: 140,
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
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--t3)",
                    letterSpacing: "0.04em",
                    marginLeft: "auto",
                  }}
                >
                  {totalJobs > 0 ? totalJobs.toLocaleString() : filtered.length}{" "}
                  roles
                </span>
              </div>
            </div>
          </ScrollReveal>
        </section>

        {/* Job grid */}
        <section
          style={{
            padding: "32px 20px 140px",
            maxWidth: 1200,
            margin: "0 auto",
          }}
        >
          {loading && jobs.length === 0 ? (
            <PageSkeleton variant="list" />
          ) : filtered.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: 80,
                color: "var(--t3)",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
              }}
            >
              No matching jobs right now
            </div>
          ) : (
            <div
              className="jobs-grid"
              style={{
                display: "grid",
                gap: 1,
                background: "var(--b)",
                border: "1px solid var(--b)",
              }}
            >
              {filtered.map((job, i) => (
                <JobCard
                  key={job.id || `${job.company}-${job.title}-${i}`}
                  job={job}
                  onClick={() => setSelectedJob(job)}
                  onRecon={() => handleRecon(job)}
                  canUseQuickReport={Boolean(user)}
                />
              ))}
            </div>
          )}

          {/* Infinite scroll sentinel */}
          {hasMore && <div ref={sentinel} style={{ height: 1 }} />}

          {loadingRef.current && jobs.length > 0 && (
            <div
              style={{
                textAlign: "center",
                padding: 40,
                color: "var(--t3)",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
              }}
            >
              Loading more...
            </div>
          )}
        </section>
      </main>

      {/* Job detail modal */}
      {selectedJob && (
        <JobDetailModal
          job={selectedJob}
          onClose={() => setSelectedJob(null)}
          canApplyWithFoxhound={canApplyWithFoxhound}
        />
      )}

      {/* Brief report modal */}
      {reconJob && reconJob.id && (
        <ReconCard
          jobId={reconJob.id}
          companyName={reconJob.company}
          jobTitle={reconJob.title}
          onClose={() => setReconJob(null)}
        />
      )}
    </>
  );
}
