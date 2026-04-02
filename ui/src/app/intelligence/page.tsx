"use client";

import {
  useState,
  useRef,
  useEffect,
  useMemo,
  useCallback,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import AppNav from "@/components/AppNav";
import AuthGuard from "@/components/AuthGuard";
import PageSkeleton from "@/components/PageSkeleton";
import { useAuth } from "@/lib/auth-context";
import {
  runCompanyBrief,
  runInterviewPrep,
  runPeopleResearch,
  runJobDiscovery,
} from "@/lib/api";

/* ═══════════════════════════════════════
   TYPES
   ═══════════════════════════════════════ */

interface GhostCheckResult {
  score: number;
  risk: "low" | "medium" | "high";
  badge: "verified" | "caution" | "ghost_risk";
  factors: string[];
}

type TabId =
  | "ghost"
  | "brief"
  | "interview"
  | "people"
  | "discovery"
  | "status";

interface TabDef {
  id: TabId;
  label: string;
  helper: string;
  autoRun: string;
  icon: ReactNode;
  requiresAuth: boolean;
}

interface ContextSeed {
  company?: string;
  role?: string;
  applicationId?: string;
}

interface ApplicationContextPayload {
  application_id?: string;
  job_id?: string | null;
  company?: string;
  role?: string;
  status?: string;
  posting_status?: string;
  submitted_at?: string | null;
  days_since_applied?: number;
  followup_day3_sent?: boolean;
  followup_day7_sent?: boolean;
  followup_day14_sent?: boolean;
  brief_ready?: boolean;
  brief_status?: string | null;
}

interface RecommendedActionPayload {
  label?: string;
  detail?: string;
  href?: string | null;
  href_label?: string | null;
  priority?: "low" | "normal" | "high";
}

function toRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function extractApplicationContext(
  result: Record<string, unknown> | null,
): ApplicationContextPayload | null {
  if (!result) return null;
  const ctx = toRecord(result.application_context);
  if (!ctx) return null;
  return {
    application_id:
      typeof ctx.application_id === "string" ? ctx.application_id : undefined,
    job_id: typeof ctx.job_id === "string" ? ctx.job_id : null,
    company: typeof ctx.company === "string" ? ctx.company : undefined,
    role: typeof ctx.role === "string" ? ctx.role : undefined,
    status: typeof ctx.status === "string" ? ctx.status : undefined,
    posting_status:
      typeof ctx.posting_status === "string" ? ctx.posting_status : undefined,
    submitted_at:
      typeof ctx.submitted_at === "string" ? ctx.submitted_at : null,
    days_since_applied:
      typeof ctx.days_since_applied === "number" ? ctx.days_since_applied : undefined,
    followup_day3_sent: Boolean(ctx.followup_day3_sent),
    followup_day7_sent: Boolean(ctx.followup_day7_sent),
    followup_day14_sent: Boolean(ctx.followup_day14_sent),
    brief_ready: Boolean(ctx.brief_ready),
    brief_status:
      typeof ctx.brief_status === "string" ? ctx.brief_status : null,
  };
}

function extractRecommendedAction(
  result: Record<string, unknown> | null,
): RecommendedActionPayload | null {
  if (!result) return null;
  const raw = result.recommended_next_action;
  if (typeof raw === "string" && raw.trim()) {
    return { label: "Recommended next action", detail: raw.trim(), priority: "normal" };
  }
  const rec = toRecord(raw);
  if (!rec) return null;
  return {
    label: typeof rec.label === "string" ? rec.label : undefined,
    detail: typeof rec.detail === "string" ? rec.detail : undefined,
    href: typeof rec.href === "string" ? rec.href : null,
    href_label: typeof rec.href_label === "string" ? rec.href_label : null,
    priority:
      rec.priority === "high" || rec.priority === "low" || rec.priority === "normal"
        ? rec.priority
        : "normal",
  };
}

function followupSummary(ctx: ApplicationContextPayload): string {
  const day3 = ctx.followup_day3_sent ? "day 3 sent" : "day 3 pending";
  const day7 = ctx.followup_day7_sent ? "day 7 sent" : "day 7 pending";
  const day14 = ctx.followup_day14_sent ? "day 14 sent" : "day 14 pending";
  return `${day3} · ${day7} · ${day14}`;
}

/* ═══════════════════════════════════════
   CONSTANTS
   ═══════════════════════════════════════ */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

const TABS: TabDef[] = [
  {
    id: "discovery",
    label: "Find Jobs",
    helper: "Search beyond your saved boards",
    autoRun: "Runs every 12 hours",
    requiresAuth: true,
    icon: (
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
    ),
  },
  {
    id: "ghost",
    label: "Ghost Check",
    helper: "Is this job real or dead?",
    autoRun: "Runs before Foxhound applies",
    requiresAuth: true,
    icon: (
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 2a7 7 0 0 0-7 7v5.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V13h2v1.5c0 .83.67 1.5 1.5 1.5h1c.83 0 1.5-.67 1.5-1.5V13h2v1.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V9a7 7 0 0 0-7-7z" />
        <circle cx="9.5" cy="9" r="1" fill="currentColor" />
        <circle cx="14.5" cy="9" r="1" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "people",
    label: "Who's Hiring",
    helper: "Find the hiring manager to reach out to",
    autoRun: "Runs after each application",
    requiresAuth: true,
    icon: (
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    id: "brief",
    label: "Company Intel",
    helper: "Culture, tech stack, red flags",
    autoRun: "Runs for 70%+ matches",
    requiresAuth: true,
    icon: (
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
        <line x1="8" y1="21" x2="16" y2="21" />
        <line x1="12" y1="17" x2="12" y2="21" />
      </svg>
    ),
  },
  {
    id: "interview",
    label: "Interview Prep",
    helper: "Questions they ask and what they pay",
    autoRun: "Runs when you advance a stage",
    requiresAuth: true,
    icon: (
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    ),
  },
  {
    id: "status",
    label: "Posting Watch",
    helper: "Still live, edited, or taken down",
    autoRun: "Monitors daily after you apply",
    requiresAuth: true,
    icon: (
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
      </svg>
    ),
  },
];

const BADGE_MAP = {
  verified: {
    label: "Verified",
    color: "var(--g)",
    bg: "rgba(52, 211, 153, 0.08)",
    border: "rgba(52, 211, 153, 0.18)",
    glow: "rgba(52, 211, 153, 0.15)",
    icon: (
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
  },
  caution: {
    label: "Caution",
    color: "var(--warning)",
    bg: "rgba(251, 191, 36, 0.08)",
    border: "rgba(251, 191, 36, 0.18)",
    glow: "rgba(251, 191, 36, 0.15)",
    icon: (
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
  },
  ghost_risk: {
    label: "Ghost Risk",
    color: "var(--error)",
    bg: "rgba(248, 113, 113, 0.08)",
    border: "rgba(248, 113, 113, 0.18)",
    glow: "rgba(248, 113, 113, 0.15)",
    icon: (
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="10" />
        <line x1="15" y1="9" x2="9" y2="15" />
        <line x1="9" y1="9" x2="15" y2="15" />
      </svg>
    ),
  },
} as const;

/* ═══════════════════════════════════════
   SHARED SUB-COMPONENTS
   ═══════════════════════════════════════ */

function Spinner({ size = 20 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      style={{ animation: "intel-spin 0.8s linear infinite" }}
      aria-hidden="true"
    >
      <circle
        cx="10"
        cy="10"
        r="8"
        stroke="rgba(255,255,255,0.15)"
        strokeWidth="2.5"
      />
      <path
        d="M10 2a8 8 0 0 1 8 8"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ShimmerBlock({ w, h }: { w?: string | number; h: number }) {
  return (
    <div
      className="intel-skel"
      style={{
        width: w ?? "100%",
        height: h,
        borderRadius: 4,
        background: "var(--sf)",
        position: "relative",
        overflow: "hidden",
      }}
    />
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        fontWeight: 500,
        color: "var(--vl)",
        letterSpacing: "0.15em",
        textTransform: "uppercase" as const,
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

function ResultCard({
  children,
  style,
}: {
  children: ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className="intel-fade-in"
      style={{
        width: "100%",
        maxWidth: 620,
        background: "var(--sf)",
        border: "1px solid var(--b)",
        borderRadius: 12,
        padding: 24,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function ScoreRing({ score, color }: { score: number; color: string }) {
  const r = 54;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;
  return (
    <svg width="136" height="136" viewBox="0 0 136 136" aria-hidden="true">
      <circle
        cx="68"
        cy="68"
        r={r}
        fill="none"
        stroke="var(--b)"
        strokeWidth="8"
      />
      <circle
        cx="68"
        cy="68"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        transform="rotate(-90 68 68)"
        style={{ transition: "stroke-dashoffset 0.8s ease-out" }}
      />
      <text
        x="68"
        y="64"
        textAnchor="middle"
        dominantBaseline="central"
        fill="var(--t)"
        fontFamily="var(--font-display)"
        fontWeight="700"
        fontSize="36"
        letterSpacing="-0.03em"
      >
        {score}
      </text>
      <text
        x="68"
        y="88"
        textAnchor="middle"
        dominantBaseline="central"
        fill="var(--t3)"
        fontFamily="var(--font-mono)"
        fontSize="9"
        letterSpacing="0.1em"
      >
        RISK SCORE
      </text>
    </svg>
  );
}

/** "Sign in to use this tool" lock screen */
function AuthGate() {
  return (
    <div
      className="intel-fade-in"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 16,
        padding: "48px 24px",
        textAlign: "center",
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: 12,
          background: "var(--vf)",
          border: "1px solid var(--bv)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--t3)",
        }}
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      </div>
      <div>
        <div
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 18,
            fontWeight: 700,
            letterSpacing: "-0.02em",
            marginBottom: 6,
          }}
        >
          Sign in to unlock
        </div>
        <p
          style={{
            fontSize: 14,
            color: "var(--t3)",
            lineHeight: 1.6,
            maxWidth: 360,
          }}
        >
          This research tool requires an account. Sign in to access company
          briefs, interview prep, and more.
        </p>
      </div>
      <Link href="/login" className="btn-violet" style={{ marginTop: 8 }}>
        Sign in
      </Link>
    </div>
  );
}

/** Shared reset button for result views */
function ResetButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        marginTop: 24,
        background: "none",
        border: "1px solid var(--b)",
        borderRadius: 8,
        padding: "10px 20px",
        color: "var(--t3)",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.06em",
        textTransform: "uppercase" as const,
        cursor: "pointer",
        transition: "all 0.2s",
        width: "100%",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "var(--bv)";
        e.currentTarget.style.color = "var(--t)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--b)";
        e.currentTarget.style.color = "var(--t3)";
      }}
    >
      {label}
    </button>
  );
}

function NextActionCard({
  label,
  detail,
  href,
  hrefLabel = "Open",
}: {
  label: string;
  detail: string;
  href?: string;
  hrefLabel?: string;
}) {
  return (
    <div
      className="intel-fade-in intel-d3"
      style={{
        marginTop: 24,
        padding: 16,
        borderRadius: 10,
        background: "rgba(139,92,246,0.06)",
        border: "1px solid rgba(139,92,246,0.15)",
      }}
    >
      <SectionLabel>Recommended Next Action</SectionLabel>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 18,
          fontWeight: 700,
          letterSpacing: "-0.02em",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.7 }}>
        {detail}
      </div>
      {href && (
        <Link
          href={href}
          style={{
            display: "inline-block",
            marginTop: 12,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--vl)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          {hrefLabel} &rarr;
        </Link>
      )}
    </div>
  );
}

function ApplicationWorkflowCard({
  context,
}: {
  context: ApplicationContextPayload | null;
}) {
  if (!context?.application_id) return null;

  const postingStatus = context.posting_status || "unknown";
  const postingColor =
    postingStatus === "active"
      ? "var(--g)"
      : postingStatus === "edited"
        ? "var(--warning)"
        : postingStatus === "removed"
          ? "var(--error)"
          : "var(--t3)";

  const days = typeof context.days_since_applied === "number" ? context.days_since_applied : null;
  const appStatus = context.status || "submitted";

  return (
    <div
      className="intel-fade-in intel-d2"
      style={{
        marginTop: 20,
        padding: 14,
        borderRadius: 10,
        background: "rgba(255,255,255,0.02)",
        border: "1px solid var(--b)",
      }}
    >
      <SectionLabel>Application Process Context</SectionLabel>
      <div style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--t2)", lineHeight: 1.6 }}>
        <div>
          <span style={{ color: "var(--t3)" }}>Status:</span>{" "}
          <span style={{ textTransform: "capitalize" }}>{String(appStatus).replaceAll("_", " ")}</span>
        </div>
        <div>
          <span style={{ color: "var(--t3)" }}>Posting:</span>{" "}
          <span style={{ color: postingColor, textTransform: "capitalize" }}>{postingStatus}</span>
        </div>
        {days !== null && (
          <div>
            <span style={{ color: "var(--t3)" }}>Applied:</span> {days} day{days === 1 ? "" : "s"} ago
          </div>
        )}
        <div>
          <span style={{ color: "var(--t3)" }}>Follow-up:</span> {followupSummary(context)}
        </div>
      </div>
      <div style={{ fontSize: 12, color: "var(--t3)", marginTop: 8, lineHeight: 1.6 }}>
        Foxhound uses this timeline to decide when to nudge, when to prep for interview rounds, and when to archive stale roles.
      </div>
    </div>
  );
}

function SeedContextCard({
  seed,
  mode = "module",
}: {
  seed?: ContextSeed;
  mode?: "module" | "page";
}) {
  if (!seed || (!seed.company && !seed.role && !seed.applicationId)) return null;

  const details = [
    seed.company ? `Company: ${seed.company}` : "",
    seed.role ? `Role: ${seed.role}` : "",
    seed.applicationId ? "Linked to a tracked application" : "",
  ].filter(Boolean);

  return (
    <div
      className="intel-fade-in"
      style={{
        marginBottom: 16,
        padding: 14,
        borderRadius: 10,
        background: "rgba(139,92,246,0.05)",
        border: "1px solid rgba(139,92,246,0.14)",
      }}
    >
      <SectionLabel>
        {mode === "page" ? "Opened From Your Foxhound Pipeline" : "Foxhound Context"}
      </SectionLabel>
      <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.7 }}>
        {details.join(" · ")}
      </div>
      <div style={{ fontSize: 12, color: "var(--t3)", marginTop: 6, lineHeight: 1.6 }}>
        Foxhound is using this context to make the research more specific, but
        you can still rerun this module manually.
      </div>
    </div>
  );
}

/** Shared inline error display */
function InlineError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="intel-fade-in"
      style={{
        marginTop: 16,
        fontSize: 13,
        color: "var(--error)",
        fontFamily: "var(--font-body)",
        display: "flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      {message}
    </div>
  );
}

/** Renders a text block with paragraphs, splitting on double-newlines */
function ProseBlock({ text }: { text: string }) {
  if (!text) return null;
  const paragraphs = text.split(/\n{2,}/);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {paragraphs.map((p, i) => (
        <p
          key={i}
          style={{
            fontSize: 14,
            color: "var(--t2)",
            lineHeight: 1.7,
            fontFamily: "var(--font-body)",
            margin: 0,
            whiteSpace: "pre-wrap",
          }}
        >
          {p.trim()}
        </p>
      ))}
    </div>
  );
}

/** Loading indicator for analysis */
function AnalyzingState({ label }: { label: string }) {
  return (
    <div
      className="intel-fade-in"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 16,
        padding: "48px 24px",
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: 12,
          background: "var(--vf)",
          border: "1px solid var(--bv)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--vl)",
        }}
      >
        <Spinner size={22} />
      </div>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--t3)",
          letterSpacing: "0.1em",
          textTransform: "uppercase" as const,
        }}
      >
        {label}
      </span>
    </div>
  );
}

/** Empty state prompt for each tab */
function EmptyPrompt({
  icon,
  heading,
  description,
}: {
  icon: ReactNode;
  heading: string;
  description: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        padding: "48px 24px",
        textAlign: "center",
      }}
    >
      <div style={{ color: "var(--t3)", opacity: 0.5 }}>{icon}</div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 16,
          fontWeight: 600,
          color: "var(--t2)",
          letterSpacing: "-0.01em",
        }}
      >
        {heading}
      </div>
      <p
        style={{
          fontSize: 13,
          color: "var(--t3)",
          lineHeight: 1.6,
          maxWidth: 380,
        }}
      >
        {description}
      </p>
    </div>
  );
}

/* ═══════════════════════════════════════
   TAB 1: GHOST DETECTOR
   ═══════════════════════════════════════ */

function GhostDetectorTab() {
  const [url, setUrl] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "result" | "error">(
    "idle",
  );
  const [result, setResult] = useState<GhostCheckResult | null>(null);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (state === "result" && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [state]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) {
      setError("Paste a job URL to check.");
      setState("error");
      return;
    }
    try {
      new URL(trimmed);
    } catch {
      setError("That doesn't look like a valid URL. Include https://");
      setState("error");
      return;
    }

    setState("loading");
    setError("");
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ghost/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `Request failed (${res.status})`);
      }
      const data: GhostCheckResult = await res.json();
      setResult(data);
      setState("result");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Something went wrong. Try again.",
      );
      setState("error");
    }
  }

  const badge = result ? BADGE_MAP[result.badge] : null;

  return (
    <div
      style={{ display: "flex", flexDirection: "column", alignItems: "center" }}
    >
      {/* Input */}
      <div style={{ width: "100%", maxWidth: 620, marginBottom: 12 }}>
        <p
          style={{
            fontSize: 14,
            color: "var(--t2)",
            lineHeight: 1.6,
            marginBottom: 20,
          }}
        >
          Paste a job posting URL to check if it&apos;s real. Works for
          any major job board or company careers page.
        </p>
        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", gap: 8, width: "100%" }}
        >
          <input
            ref={inputRef}
            type="url"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              if (state === "error") setState("idle");
            }}
            placeholder="https://boards.greenhouse.io/company/jobs/123456"
            aria-label="Job posting URL"
            className="input"
            style={{
              flex: 1,
              padding: "14px 18px",
              fontSize: 15,
              borderRadius: 10,
              background: "var(--sf)",
              border: `1px solid ${state === "error" ? "var(--error)" : "var(--b)"}`,
            }}
          />
          <button
            type="submit"
            disabled={state === "loading"}
            className="btn-violet"
            style={{
              borderRadius: 10,
              padding: "14px 28px",
              fontSize: 12,
              letterSpacing: "0.08em",
              minWidth: 100,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              opacity: state === "loading" ? 0.7 : 1,
              cursor: state === "loading" ? "not-allowed" : "pointer",
            }}
          >
            {state === "loading" ? (
              <>
                <Spinner /> Checking
              </>
            ) : (
              "Check"
            )}
          </button>
        </form>
      </div>

      {/* Error */}
      {state === "error" && error && (
        <div
          role="alert"
          className="intel-fade-in"
          style={{
            marginTop: 8,
            fontSize: 13,
            color: "var(--error)",
            fontFamily: "var(--font-body)",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          {error}
        </div>
      )}

      {/* Loading */}
      {state === "loading" && <AnalyzingState label="Analyzing posting..." />}

      {/* Result */}
      {state === "result" && result && badge && (
        <div
          ref={resultRef}
          className="intel-fade-in"
          style={{
            marginTop: 32,
            width: "100%",
            maxWidth: 560,
            background: "var(--sf)",
            border: `1px solid ${badge.border}`,
            borderRadius: 16,
            padding: 32,
            boxShadow: `0 0 60px ${badge.glow}, 0 8px 32px rgba(0,0,0,0.4)`,
          }}
        >
          {/* Badge + Score */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 24,
              flexWrap: "wrap",
            }}
          >
            <div className="intel-fade-in intel-d1">
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 16px",
                  borderRadius: 8,
                  background: badge.bg,
                  border: `1px solid ${badge.border}`,
                  color: badge.color,
                  fontFamily: "var(--font-display)",
                  fontWeight: 700,
                  fontSize: 16,
                  letterSpacing: "-0.01em",
                  textTransform: "uppercase" as const,
                }}
              >
                {badge.icon}
                {badge.label}
              </div>
              <div
                style={{
                  marginTop: 12,
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--t3)",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase" as const,
                  maxWidth: 260,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {url}
              </div>
            </div>
            <div className="intel-fade-in intel-d2">
              <ScoreRing score={result.score} color={badge.color} />
            </div>
          </div>

          {/* Progress bar */}
          <div className="intel-fade-in intel-d3" style={{ marginTop: 28 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--t3)",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase" as const,
                }}
              >
                Risk level
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: badge.color,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase" as const,
                  fontWeight: 600,
                }}
              >
                {result.risk}
              </span>
            </div>
            <div
              style={{
                width: "100%",
                height: 4,
                background: "var(--el)",
                borderRadius: 2,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${result.score}%`,
                  height: "100%",
                  background: badge.color,
                  borderRadius: 2,
                  animation: "intel-bar-fill 0.8s ease-out both",
                }}
              />
            </div>
          </div>

          {/* Divider */}
          <div
            style={{
              marginTop: 28,
              marginBottom: 24,
              height: 1,
              background:
                "linear-gradient(90deg, transparent, var(--b), transparent)",
            }}
          />

          {/* Factors */}
          <div className="intel-fade-in intel-d4">
            <SectionLabel>Analysis</SectionLabel>
            <ul
              style={{
                listStyle: "none",
                padding: 0,
                margin: 0,
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              {result.factors.map((factor, i) => (
                <li
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    fontSize: 14,
                    color: "var(--t2)",
                    lineHeight: 1.6,
                    fontFamily: "var(--font-body)",
                  }}
                >
                  <span
                    style={{
                      width: 5,
                      height: 5,
                      borderRadius: "50%",
                      background: badge.color,
                      boxShadow: `0 0 6px ${badge.glow}`,
                      flexShrink: 0,
                      marginTop: 8,
                    }}
                  />
                  {factor}
                </li>
              ))}
            </ul>
          </div>

          <NextActionCard
            label={
              result.badge === "verified"
                ? "Keep this role in Foxhound’s active search"
                : result.badge === "ghost_risk"
                  ? "Deprioritize this posting and redirect effort elsewhere"
                  : "Validate this posting before you spend more time on it"
            }
            detail={
              result.badge === "verified"
                ? "Foxhound sees enough live signal to keep tracking this posting. If it fits your profile, move it into applications and let Status Tracker monitor it."
                : result.badge === "ghost_risk"
                  ? "This posting has enough ghost-job risk that Foxhound should not spend more follow-up energy here unless you already have traction with the team."
                  : "The signal is mixed. Save the role, but verify the live page again or compare it against other strong matches before applying."
            }
          />

          {/* Reset */}
          <button
            type="button"
            onClick={() => {
              setUrl("");
              setResult(null);
              setState("idle");
              setTimeout(() => inputRef.current?.focus(), 50);
            }}
            style={{
              marginTop: 28,
              background: "none",
              border: "1px solid var(--b)",
              borderRadius: 8,
              padding: "10px 20px",
              color: "var(--t3)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: "0.06em",
              textTransform: "uppercase" as const,
              cursor: "pointer",
              transition: "all 0.2s",
              width: "100%",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = "var(--bv)";
              e.currentTarget.style.color = "var(--t)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = "var(--b)";
              e.currentTarget.style.color = "var(--t3)";
            }}
          >
            Check another URL
          </button>

        </div>
      )}

      {/* Idle empty state */}
      {state === "idle" && !result && (
        <EmptyPrompt
          icon={
            <svg
              width="40"
              height="40"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 2a7 7 0 0 0-7 7v5.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V13h2v1.5c0 .83.67 1.5 1.5 1.5h1c.83 0 1.5-.67 1.5-1.5V13h2v1.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V9a7 7 0 0 0-7-7z" />
              <circle cx="9.5" cy="9" r="1" fill="currentColor" />
              <circle cx="14.5" cy="9" r="1" fill="currentColor" />
            </svg>
          }
          heading="Detect ghost job postings"
          description="Ghost jobs are postings that were never meant to be filled. Paste any job URL above to check if it's a real opportunity."
        />
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   TAB 2: COMPANY BRIEF
   ═══════════════════════════════════════ */

function CompanyBriefTab({ seed }: { seed?: ContextSeed }) {
  const { user } = useAuth();
  const [company, setCompany] = useState(seed?.company || "");
  const [state, setState] = useState<"idle" | "loading" | "result" | "error">("idle");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  if (!user) return <AuthGate />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = company.trim();
    if (!trimmed) return;
    setState("loading");
    setError("");
    setResult(null);
    try {
      const data = await runCompanyBrief(trimmed, seed?.applicationId);
      setResult(data);
      setState("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research failed. Try again.");
      setState("error");
    }
  }

  function handleReset() {
    setCompany("");
    setResult(null);
    setError("");
    setState("idle");
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  const confidence = result?.confidence as string | undefined;
  const confidenceColor = confidence === "high" ? "var(--g)" : confidence === "medium" ? "var(--warning)" : "var(--t3)";
  const appContext = extractApplicationContext(result);
  const guidedAction = extractRecommendedAction(result);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      {/* Input */}
      <div style={{ width: "100%", maxWidth: 620, marginBottom: 12 }}>
        <SeedContextCard seed={seed} />
        <p style={{ fontSize: 14, color: "var(--t2)", lineHeight: 1.6, marginBottom: 20 }}>
          Get a quick overview of any company: what they do, their tech stack,
          how aggressively they&apos;re hiring, and insider tips for your application.
        </p>
        <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8 }}>
          <input
            ref={inputRef}
            type="text"
            value={company}
            onChange={(e) => { setCompany(e.target.value); if (state === "error") setState("idle"); }}
            placeholder="e.g. Stripe, Vercel, Figma..."
            aria-label="Company name"
            className="input"
            style={{ flex: 1, padding: "14px 18px", fontSize: 15, borderRadius: 10, background: "var(--sf)" }}
            disabled={state === "loading"}
          />
          <button
            type="submit"
            disabled={state === "loading"}
            className="btn-violet"
            style={{
              borderRadius: 10, padding: "14px 28px", fontSize: 12,
              letterSpacing: "0.08em", minWidth: 100,
              display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
              opacity: state === "loading" ? 0.7 : 1,
              cursor: state === "loading" ? "not-allowed" : "pointer",
            }}
          >
            {state === "loading" ? <><Spinner /> Researching</> : "Research"}
          </button>
        </form>
      </div>

      {/* Error */}
      {state === "error" && error && <InlineError message={error} />}

      {/* Loading */}
      {state === "loading" && <AnalyzingState label="Researching company..." />}

      {/* Result */}
      {state === "result" && result && (
        <ResultCard style={{ marginTop: 24 }}>
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
            <div>
              <SectionLabel>Company Brief</SectionLabel>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", textTransform: "uppercase" as const }}>
                {String(result.company || company)}
              </div>
            </div>
            {confidence && (
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                fontFamily: "var(--font-mono)", fontSize: 10, color: confidenceColor,
                letterSpacing: "0.1em", textTransform: "uppercase" as const,
                padding: "4px 10px", borderRadius: 6,
                background: confidence === "high" ? "rgba(52,211,153,0.08)" : confidence === "medium" ? "rgba(251,191,36,0.08)" : "rgba(255,255,255,0.04)",
                border: `1px solid ${confidence === "high" ? "rgba(52,211,153,0.18)" : confidence === "medium" ? "rgba(251,191,36,0.18)" : "var(--b)"}`,
              }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: confidenceColor }} />
                {confidence} confidence
              </span>
            )}
          </div>

          {/* Summary */}
          {typeof result.summary === "string" && result.summary && (
            <div className="intel-fade-in" style={{ marginBottom: 24 }}>
              <ProseBlock text={result.summary} />
            </div>
          )}

          {/* Hiring velocity */}
          {typeof result.hiring_velocity === "string" && result.hiring_velocity && (
            <div className="intel-fade-in intel-d1" style={{ marginBottom: 24 }}>
              <SectionLabel>Hiring Velocity</SectionLabel>
              <div style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                fontSize: 14, fontWeight: 500, color: "var(--t)",
                fontFamily: "var(--font-body)",
                textTransform: "capitalize" as const,
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: "50%",
                  background: result.hiring_velocity === "growing" ? "var(--g)" : "var(--warning)",
                }} />
                {result.hiring_velocity}
              </div>
            </div>
          )}

          {/* Tech stack pills */}
          {Array.isArray(result.tech_stack) && (result.tech_stack as string[]).length > 0 && (
            <div className="intel-fade-in intel-d2" style={{ marginBottom: 24 }}>
              <SectionLabel>Tech Stack</SectionLabel>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {(result.tech_stack as string[]).map((tech, i) => (
                  <span key={i} style={{
                    padding: "5px 12px", borderRadius: 6,
                    background: "var(--vf)", border: "1px solid var(--bv)",
                    fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--vl)",
                    letterSpacing: "0.02em",
                  }}>
                    {tech}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Insider tip */}
          {typeof result.insider_tip === "string" && result.insider_tip && (
            <div className="intel-fade-in intel-d3" style={{
              padding: 16, borderRadius: 10,
              background: "rgba(139,92,246,0.06)",
              border: "1px solid rgba(139,92,246,0.15)",
            }}>
              <SectionLabel>Insider Tip</SectionLabel>
              <p style={{ fontSize: 14, color: "var(--vl)", lineHeight: 1.7, fontFamily: "var(--font-body)", margin: 0, fontStyle: "italic" }}>
                {String(result.insider_tip)}
              </p>
            </div>
          )}

          <ApplicationWorkflowCard context={appContext} />

          <NextActionCard
            label={
              guidedAction?.label ||
              (typeof result.hiring_velocity === "string" && result.hiring_velocity === "growing"
                ? "Tailor your outreach around why this team is hiring now"
                : seed?.applicationId
                  ? "Use this brief to sharpen your follow-up before you reach out"
                  : "Use this brief to sharpen your positioning before you follow up")
            }
            detail={
              guidedAction?.detail ||
              (typeof result.insider_tip === "string" && result.insider_tip
                ? result.insider_tip
                : seed?.role
                  ? `Pull the strongest company signal from this brief into your next ${seed.role} outreach note, application answer, or interview story.`
                  : "Pull the strongest company signal from this brief into your next outreach note, application answer, or interview story.")
            }
            href={guidedAction?.href || (seed?.applicationId ? `/brief/${seed.applicationId}` : undefined)}
            hrefLabel={guidedAction?.href_label || "Open Foxhound Brief"}
          />

          <ResetButton onClick={handleReset} label="Research another company" />
        </ResultCard>
      )}

      {/* Idle empty state */}
      {state === "idle" && !result && (
        <EmptyPrompt
          icon={
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
          }
          heading="Research any company"
          description="Enter a company name to get a quick intel brief powered by live data."
        />
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   TAB 3: INTERVIEW PREP
   ═══════════════════════════════════════ */

function InterviewPrepTab({ seed }: { seed?: ContextSeed }) {
  const { user } = useAuth();
  const [company, setCompany] = useState(seed?.company || "");
  const [role, setRole] = useState(seed?.role || "");
  const [state, setState] = useState<"idle" | "loading" | "result" | "error">("idle");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  if (!user) return <AuthGate />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = company.trim();
    if (!trimmed) return;
    setState("loading");
    setError("");
    setResult(null);
    try {
      const data = await runInterviewPrep(
        trimmed,
        role.trim() || undefined,
        seed?.applicationId,
      );
      setResult(data);
      setState("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research failed. Try again.");
      setState("error");
    }
  }

  function handleReset() {
    setCompany("");
    setRole("");
    setResult(null);
    setError("");
    setState("idle");
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  // Build sections from result, filtering out empty/missing fields
  const sections: { label: string; content: string }[] = [];
  if (result) {
    if (result.glassdoor) sections.push({ label: "Interview Experiences", content: result.glassdoor as string });
    if (result.reddit) sections.push({ label: "Candidate Insights", content: result.reddit as string });
    if (result.coding_questions) sections.push({ label: "Common Questions", content: result.coding_questions as string });
    if (result.salary_offers) sections.push({ label: "Compensation Data", content: result.salary_offers as string });
  }

  const sourcesFound = Array.isArray(result?.sources_found) ? (result.sources_found as string[]).length : 0;
  const appContext = extractApplicationContext(result);
  const guidedAction = extractRecommendedAction(result);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      {/* Input */}
      <div style={{ width: "100%", maxWidth: 620, marginBottom: 12 }}>
        <SeedContextCard seed={seed} />
        <p style={{ fontSize: 14, color: "var(--t2)", lineHeight: 1.6, marginBottom: 20 }}>
          Get interview questions, difficulty ratings, and process insights
          tailored to your profile and target roles.
        </p>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              ref={inputRef}
              type="text"
              value={company}
              onChange={(e) => { setCompany(e.target.value); if (state === "error") setState("idle"); }}
              placeholder="Company (e.g. Google, Netflix, Airbnb)"
              aria-label="Company name"
              className="input"
              style={{ flex: 1, padding: "14px 18px", fontSize: 15, borderRadius: 10, background: "var(--sf)" }}
              disabled={state === "loading"}
            />
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="Role (optional)"
              aria-label="Role"
              className="input"
              style={{ flex: 1, padding: "14px 18px", fontSize: 14, borderRadius: 10, background: "var(--sf)" }}
              disabled={state === "loading"}
            />
          </div>
          <button
            type="submit"
            disabled={state === "loading"}
            className="btn-violet"
            style={{
              borderRadius: 10, padding: "14px 28px", fontSize: 12,
              letterSpacing: "0.08em", alignSelf: "flex-start",
              display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
              opacity: state === "loading" ? 0.7 : 1,
              cursor: state === "loading" ? "not-allowed" : "pointer",
            }}
          >
            {state === "loading" ? <><Spinner /> Preparing</> : "Prepare"}
          </button>
        </form>
      </div>

      {/* Error */}
      {state === "error" && error && <InlineError message={error} />}

      {/* Loading */}
      {state === "loading" && <AnalyzingState label="Gathering interview data..." />}

      {/* Result */}
      {state === "result" && result && (
        <ResultCard style={{ marginTop: 24 }}>
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
            <div>
              <SectionLabel>Interview Prep</SectionLabel>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", textTransform: "uppercase" as const }}>
                {String(result.company || company)}
                {typeof result.role === "string" && result.role && <span style={{ color: "var(--t3)", fontWeight: 500, fontSize: 16, marginLeft: 8 }}>{result.role}</span>}
              </div>
            </div>
            {sourcesFound > 0 && (
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--g)",
                letterSpacing: "0.1em", textTransform: "uppercase" as const,
                padding: "4px 10px", borderRadius: 6,
                background: "rgba(52,211,153,0.08)", border: "1px solid rgba(52,211,153,0.18)",
              }}>
                {sourcesFound} {sourcesFound === 1 ? "source" : "sources"}
              </span>
            )}
          </div>

          {/* Sections */}
          {sections.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
              {sections.map((section, i) => (
                <div key={section.label} className={`intel-fade-in intel-d${Math.min(i + 1, 4)}`}>
                  <SectionLabel>{section.label}</SectionLabel>
                  <ProseBlock text={section.content} />
                </div>
              ))}
            </div>
          ) : (
            <p style={{ fontSize: 14, color: "var(--t3)", lineHeight: 1.6, fontFamily: "var(--font-body)" }}>
              {String(result.message || "") || "No detailed interview data found for this company."}
            </p>
          )}

          <ApplicationWorkflowCard context={appContext} />

          <NextActionCard
            label={
              guidedAction?.label ||
              (seed?.applicationId
                ? "Turn this into your next-round prep plan"
                : "Build your first three interview stories now")
            }
            detail={
              guidedAction?.detail ||
              (role
                ? `Use this prep to rehearse the strongest examples from your background for ${role} interviews, then revisit it once Foxhound detects a process update.`
                : seed?.applicationId
                  ? "Foxhound opened this from a tracked application. Focus on the first likely round now, then come back once the process advances."
                  : "Use this prep to rehearse your strongest stories now, then revisit it once Foxhound detects a process update.")
            }
            href={guidedAction?.href || (seed?.applicationId ? `/brief/${seed.applicationId}` : undefined)}
            hrefLabel={guidedAction?.href_label || "Open Foxhound Brief"}
          />

          <ResetButton onClick={handleReset} label="Research another company" />
        </ResultCard>
      )}

      {/* Idle empty state */}
      {state === "idle" && !result && (
        <EmptyPrompt
          icon={
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          }
          heading="Prepare for any interview"
          description="Enter a company name to research common questions, process stages, and what candidates say about interviewing there."
        />
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   TAB 4: PEOPLE RESEARCH
   ═══════════════════════════════════════ */

function PeopleResearchTab({ seed }: { seed?: ContextSeed }) {
  const { user } = useAuth();
  const [company, setCompany] = useState(seed?.company || "");
  const [role, setRole] = useState(seed?.role || "");
  const [state, setState] = useState<"idle" | "loading" | "result" | "error">("idle");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  if (!user) return <AuthGate />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = company.trim();
    if (!trimmed) return;
    setState("loading");
    setError("");
    setResult(null);
    try {
      const data = await runPeopleResearch(
        trimmed,
        role.trim() || undefined,
        seed?.applicationId,
      );
      setResult(data);
      setState("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "People research failed. Try again.");
      setState("error");
    }
  }

  function handleReset() {
    setCompany("");
    setRole("");
    setResult(null);
    setError("");
    setState("idle");
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  const contacts = Array.isArray(result?.contacts) ? (result.contacts as Array<{ name?: string; title?: string; linkedin_url?: string; connection_angle?: string; relevance?: string }>) : [];
  const managerSignals = (result?.manager_signals as Record<string, unknown> | undefined) || null;
  const searchUrls = (result?.search_urls as Record<string, string> | undefined) || null;
  const outreach = (result?.outreach as Record<string, unknown> | undefined) || null;
  const overlap = (result?.overlap as Record<string, unknown> | undefined) || null;
  const likelyTitle = typeof managerSignals?.likely_title === "string" ? managerSignals.likely_title : null;
  const department = typeof managerSignals?.department === "string" ? managerSignals.department : null;
  const confidence = typeof managerSignals?.confidence === "string" ? managerSignals.confidence : null;
  const linkedinNote = typeof outreach?.linkedin_note === "string" ? outreach.linkedin_note : "";
  const emailSubject = typeof outreach?.email_subject === "string" ? outreach.email_subject : "";
  const emailBody = typeof outreach?.email_body === "string" ? outreach.email_body : "";
  const sharedSkills = Array.isArray(overlap?.shared_skills) ? overlap.shared_skills as string[] : [];
  const overlapScore = typeof overlap?.overlap_score === "number" ? overlap.overlap_score : null;
  const appContext = extractApplicationContext(result);
  const guidedAction = extractRecommendedAction(result);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      {/* Input */}
      <div style={{ width: "100%", maxWidth: 620, marginBottom: 12 }}>
        <SeedContextCard seed={seed} />
        <p style={{ fontSize: 14, color: "var(--t2)", lineHeight: 1.6, marginBottom: 20 }}>
          Identify the most relevant person for a role, uncover nearby
          contacts at the company, and get focused outreach angles.
        </p>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              ref={inputRef}
              type="text"
              value={company}
              onChange={(e) => { setCompany(e.target.value); if (state === "error") setState("idle"); }}
              placeholder="Company (e.g. Notion, Linear, Anthropic)"
              aria-label="Company name"
              className="input"
              style={{ flex: 1, padding: "14px 18px", fontSize: 15, borderRadius: 10, background: "var(--sf)" }}
              disabled={state === "loading"}
            />
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="Role (optional)"
              aria-label="Role"
              className="input"
              style={{ flex: 1, padding: "14px 18px", fontSize: 14, borderRadius: 10, background: "var(--sf)" }}
              disabled={state === "loading"}
            />
          </div>
          <button
            type="submit"
            disabled={state === "loading"}
            className="btn-violet"
            style={{
              borderRadius: 10, padding: "14px 28px", fontSize: 12,
              letterSpacing: "0.08em", alignSelf: "flex-start",
              display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
              opacity: state === "loading" ? 0.7 : 1,
              cursor: state === "loading" ? "not-allowed" : "pointer",
            }}
          >
            {state === "loading" ? <><Spinner /> Researching</> : "Start Research"}
          </button>
        </form>
      </div>

      {/* Error */}
      {state === "error" && error && <InlineError message={error} />}

      {/* Loading */}
      {state === "loading" && <AnalyzingState label="Identifying the right people..." />}

      {/* Result */}
      {state === "result" && result && (
        <ResultCard style={{ marginTop: 24 }}>
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
            <div>
              <SectionLabel>People Research</SectionLabel>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", textTransform: "uppercase" as const }}>
                {String(result.company || company)}
              </div>
            </div>
            {(likelyTitle || typeof result.contacts_count === "number" || typeof result.count === "number") && (
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--vl)",
                letterSpacing: "0.1em", textTransform: "uppercase" as const,
                padding: "4px 10px", borderRadius: 6,
                background: "var(--vf)", border: "1px solid var(--bv)",
              }}>
                {likelyTitle ? "target found" : `${(result.contacts_count || result.count) as number} contacts`}
              </span>
            )}
          </div>

          {(likelyTitle || searchUrls || overlap || outreach) && (
            <div style={{ display: "grid", gap: 16, marginBottom: 20 }}>
              <div style={{ padding: 16, background: "rgba(255,255,255,0.02)", border: "1px solid var(--b)", borderRadius: 8 }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--vl)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
                  Best Contact
                </div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em" }}>
                  {likelyTitle || "No clear manager identified"}
                </div>
                {(department || confidence) && (
                  <div style={{ fontSize: 13, color: "var(--t2)", marginTop: 6, lineHeight: 1.6 }}>
                    {[department ? `Department: ${department}` : "", confidence ? `Confidence: ${confidence}` : ""].filter(Boolean).join(" · ")}
                  </div>
                )}
              </div>

              {(searchUrls?.linkedin || searchUrls?.google) && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {searchUrls?.linkedin && (
                    <a href={searchUrls.linkedin} target="_blank" rel="noopener noreferrer" className="btn-violet" style={{ borderRadius: 10, padding: "12px 16px", fontSize: 11, letterSpacing: "0.06em" }}>
                      Open LinkedIn Search
                    </a>
                  )}
                  {searchUrls?.google && (
                    <a href={searchUrls.google} target="_blank" rel="noopener noreferrer" className="btn-ghost" style={{ borderRadius: 10, padding: "12px 16px", fontSize: 11, letterSpacing: "0.06em" }}>
                      Open Google Search
                    </a>
                  )}
                </div>
              )}

              {overlap && (
                <div style={{ padding: 16, background: "rgba(255,255,255,0.02)", border: "1px solid var(--b)", borderRadius: 8 }}>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--vl)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
                    Why You Match
                  </div>
                  {overlapScore !== null && (
                    <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em", marginBottom: 8 }}>
                      {overlapScore}%
                    </div>
                  )}
                  <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.7 }}>
                    {sharedSkills.length > 0 ? `Shared skills: ${sharedSkills.slice(0, 5).join(", ")}` : "Foxhound found contextual overlap for this role even without strong skill matches."}
                  </div>
                </div>
              )}

              {(linkedinNote || emailBody) && (
                <div style={{ display: "grid", gap: 12 }}>
                  {linkedinNote && (
                    <div style={{ padding: 16, background: "rgba(255,255,255,0.02)", border: "1px solid var(--b)", borderRadius: 8 }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--vl)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
                        LinkedIn Note
                      </div>
                      <ProseBlock text={linkedinNote} />
                    </div>
                  )}
                  {emailBody && (
                    <div style={{ padding: 16, background: "rgba(255,255,255,0.02)", border: "1px solid var(--b)", borderRadius: 8 }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--vl)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
                        Email Draft
                      </div>
                      {emailSubject && (
                        <div style={{ fontSize: 12, color: "var(--t3)", marginBottom: 8 }}>
                          Subject: {emailSubject}
                        </div>
                      )}
                      <ProseBlock text={emailBody} />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Additional contacts */}
          {contacts.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--t3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
                Other Useful Contacts
              </div>
              {contacts.map((contact, i) => {
                const relevanceColor = contact.relevance === "high" ? "var(--g)" : contact.relevance === "medium" ? "var(--warning)" : "var(--t3)";
                return (
                  <div
                    key={i}
                    className={`intel-fade-in intel-d${Math.min(i + 1, 4)}`}
                    style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "14px 16px", background: "rgba(255,255,255,0.02)",
                      border: "1px solid var(--b)", borderRadius: 8,
                      transition: "border-color 0.2s",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--bv)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--b)"; }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                        <span style={{ fontFamily: "var(--font-body)", fontSize: 14, fontWeight: 600, color: "var(--t)" }}>
                          {contact.name || "Unknown"}
                        </span>
                        {contact.relevance && (
                          <span style={{
                            width: 6, height: 6, borderRadius: "50%",
                            background: relevanceColor, flexShrink: 0,
                          }} />
                        )}
                      </div>
                      {contact.title && (
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t3)", marginBottom: 4 }}>
                          {contact.title}
                        </div>
                      )}
                      {contact.connection_angle && (
                        <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.5, fontFamily: "var(--font-body)" }}>
                          {contact.connection_angle}
                        </div>
                      )}
                    </div>
                    {contact.linkedin_url && (
                      <a
                        href={contact.linkedin_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`View ${contact.name || "contact"} on LinkedIn`}
                        style={{
                          flexShrink: 0, marginLeft: 12,
                          width: 32, height: 32, borderRadius: 8,
                          background: "var(--vf)", border: "1px solid var(--bv)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          color: "var(--vl)", transition: "all 0.2s",
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(139,92,246,0.15)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "var(--vf)"; }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                          <polyline points="15 3 21 3 21 9" />
                          <line x1="10" y1="14" x2="21" y2="3" />
                        </svg>
                      </a>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <p style={{ fontSize: 14, color: "var(--t3)", lineHeight: 1.6, fontFamily: "var(--font-body)" }}>
              {String(result.message || "") || "Foxhound could not identify a strong contact for this company yet."}
            </p>
          )}

          <ApplicationWorkflowCard context={appContext} />

          <NextActionCard
            label={
              guidedAction?.label ||
              (likelyTitle
                ? "Reach out to the best contact first"
                : "Use the search links to verify the right contact")
            }
            detail={
              guidedAction?.detail ||
              (likelyTitle
                ? seed?.applicationId
                  ? "Foxhound found a focused contact path for this tracked application. Use the outreach draft now, then fall back to the additional contacts if the likely hiring manager is unclear."
                  : "Foxhound found a focused contact path. Use the outreach draft, then fall back to the additional contacts if the likely hiring manager is unclear."
                : "Foxhound found partial people context. Use the search links and overlap summary to confirm the most relevant contact before sending outreach.")
            }
            href={guidedAction?.href || (seed?.applicationId ? `/brief/${seed.applicationId}` : undefined)}
            hrefLabel={guidedAction?.href_label || "Open Foxhound Brief"}
          />

          <ResetButton onClick={handleReset} label="Research another company" />
        </ResultCard>
      )}

      {/* Idle empty state */}
      {state === "idle" && !result && (
        <EmptyPrompt
          icon={
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
          }
          heading="Research the right people"
          description="Enter a company to find the best person to contact, see nearby connections, and generate focused outreach."
        />
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   TAB 5: JOB DISCOVERY
   ═══════════════════════════════════════ */

function JobDiscoveryTab({ seed }: { seed?: ContextSeed }) {
  const { user } = useAuth();
  const [role, setRole] = useState(seed?.role || "");
  const [location, setLocation] = useState("");
  const [industry, setIndustry] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "result" | "error">("idle");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  if (!user) return <AuthGate />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmedRole = role.trim();
    if (!trimmedRole) return;
    setState("loading");
    setError("");
    setResult(null);
    try {
      const data = await runJobDiscovery(
        trimmedRole,
        trimmedRole,
        location.trim() || undefined,
        industry.trim() || undefined,
        seed?.applicationId,
      );
      setResult(data);
      setState("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Discovery failed. Try again.");
      setState("error");
    }
  }

  function handleReset() {
    setRole("");
    setLocation("");
    setIndustry("");
    setResult(null);
    setError("");
    setState("idle");
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  const jobs = Array.isArray(result?.jobs) ? (result.jobs as Array<{ title?: string; company?: string; location?: string; apply_url?: string; description?: string }>) : [];
  const searchSummary = [role, location, industry].filter(Boolean).join(" / ");
  const appContext = extractApplicationContext(result);
  const guidedAction = extractRecommendedAction(result);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      {/* Input */}
      <div style={{ width: "100%", maxWidth: 620, marginBottom: 12 }}>
        <SeedContextCard seed={seed} />
        <p style={{ fontSize: 14, color: "var(--t2)", lineHeight: 1.6, marginBottom: 20 }}>
          Search for jobs by role, location, and industry. Find matching
          opportunities across all integrated sources.
        </p>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <input
            ref={inputRef}
            type="text"
            value={role}
            onChange={(e) => { setRole(e.target.value); if (state === "error") setState("idle"); }}
            placeholder="Role (e.g. Senior Frontend Engineer)"
            aria-label="Job role"
            className="input"
            style={{ padding: "14px 18px", fontSize: 15, borderRadius: 10, background: "var(--sf)" }}
            disabled={state === "loading"}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Location (optional)"
              aria-label="Location"
              className="input"
              style={{ flex: 1, padding: "14px 18px", fontSize: 14, borderRadius: 10, background: "var(--sf)" }}
              disabled={state === "loading"}
            />
            <input
              type="text"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="Industry (optional)"
              aria-label="Industry"
              className="input"
              style={{ flex: 1, padding: "14px 18px", fontSize: 14, borderRadius: 10, background: "var(--sf)" }}
              disabled={state === "loading"}
            />
          </div>
          <button
            type="submit"
            disabled={state === "loading"}
            className="btn-violet"
            style={{
              borderRadius: 10, padding: "14px 28px", fontSize: 12,
              letterSpacing: "0.08em", alignSelf: "flex-start",
              display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
              opacity: state === "loading" ? 0.7 : 1,
              cursor: state === "loading" ? "not-allowed" : "pointer",
            }}
          >
            {state === "loading" ? <><Spinner /> Discovering</> : "Discover"}
          </button>
        </form>
      </div>

      {/* Error */}
      {state === "error" && error && <InlineError message={error} />}

      {/* Loading */}
      {state === "loading" && <AnalyzingState label="Searching for opportunities..." />}

      {/* Result */}
      {state === "result" && result && (
        <div style={{ width: "100%", maxWidth: 620, marginTop: 24 }}>
          {/* Header */}
          <div className="intel-fade-in" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
            <div>
              <SectionLabel>Job Discovery</SectionLabel>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em" }}>
                {searchSummary}
              </div>
            </div>
            {typeof result.count === "number" && (
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--g)",
                letterSpacing: "0.1em", textTransform: "uppercase" as const,
                padding: "4px 10px", borderRadius: 6,
                background: "rgba(52,211,153,0.08)", border: "1px solid rgba(52,211,153,0.18)",
              }}>
                {result.count} {(result.count as number) === 1 ? "job" : "jobs"}
              </span>
            )}
          </div>

          {/* Job cards */}
          {jobs.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {jobs.map((job, i) => (
                <div
                  key={i}
                  className={`intel-fade-in intel-d${Math.min(i + 1, 4)}`}
                  style={{
                    padding: "18px 20px", background: "var(--sf)",
                    border: "1px solid var(--b)", borderRadius: 10,
                    transition: "border-color 0.2s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--bv)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--b)"; }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontFamily: "var(--font-body)", fontSize: 15, fontWeight: 600, color: "var(--t)", marginBottom: 4, lineHeight: 1.3 }}>
                        {job.title || "Untitled Position"}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                        {job.company && (
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--vl)" }}>
                            {job.company}
                          </span>
                        )}
                        {job.company && job.location && (
                          <span style={{ width: 3, height: 3, borderRadius: "50%", background: "var(--t3)" }} />
                        )}
                        {job.location && (
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t3)" }}>
                            {job.location}
                          </span>
                        )}
                      </div>
                      {job.description && (
                        <p style={{
                          fontSize: 13, color: "var(--t2)", lineHeight: 1.6,
                          fontFamily: "var(--font-body)", margin: 0,
                          display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" as const,
                          overflow: "hidden",
                        }}>
                          {job.description}
                        </p>
                      )}
                    </div>
                    {job.apply_url && (
                      <a
                        href={job.apply_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`Apply to ${job.title || "this position"}`}
                        style={{
                          flexShrink: 0,
                          padding: "8px 16px", borderRadius: 8,
                          background: "var(--vf)", border: "1px solid var(--bv)",
                          fontFamily: "var(--font-mono)", fontSize: 10,
                          letterSpacing: "0.1em", textTransform: "uppercase" as const,
                          color: "var(--vl)", textDecoration: "none",
                          transition: "all 0.2s", whiteSpace: "nowrap",
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(139,92,246,0.15)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "var(--vf)"; }}
                      >
                        Apply
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ fontSize: 14, color: "var(--t3)", lineHeight: 1.6, fontFamily: "var(--font-body)", textAlign: "center", padding: "32px 0" }}>
              {String(result.message || "") || "No matching jobs found. Try different search criteria."}
            </p>
          )}

          <ApplicationWorkflowCard context={appContext} />

          <NextActionCard
            label={guidedAction?.label || "Push the strongest matches into your search"}
            detail={
              guidedAction?.detail ||
              (seed?.role
                ? `Foxhound is already anchoring discovery around ${seed.role}. Use the strongest matches to expand your search, and remember that Foxhound can keep hunting without a resume but still needs one before it can apply.`
                : "Use discovery to surface options, then move the best ones into Foxhound’s application and research flow. If your resume is still missing, Foxhound can keep hunting but it still needs one before it can apply.")
            }
            href={guidedAction?.href ?? undefined}
            hrefLabel={guidedAction?.href_label || "Open Pipeline"}
          />

          <ResetButton onClick={handleReset} label="Search again" />
        </div>
      )}

      {/* Idle empty state */}
      {state === "idle" && !result && (
        <EmptyPrompt
          icon={
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          }
          heading="Discover matching jobs"
          description="Enter a role and optional location or industry to search across job boards for matching opportunities."
        />
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   TAB 6: STATUS TRACKER
   ═══════════════════════════════════════ */

interface TrackedApp {
  id: string;
  status: string;
  posting_status: string;
  job: { title: string; company: string; ats_type: string };
  created_at: string | null;
  submitted_at: string | null;
  days_since_applied?: number;
}

const POSTING_COLORS: Record<string, string> = {
  active: "var(--g)",
  edited: "var(--warning)",
  removed: "var(--error)",
  reposted: "var(--vl)",
  unknown: "var(--t3)",
};

function StatusTrackerTab({ seed }: { seed?: ContextSeed }) {
  const [apps, setApps] = useState<TrackedApp[]>([]);
  const [loadingApps, setLoadingApps] = useState(true);
  const [url, setUrl] = useState("");
  const [checkState, setCheckState] = useState<"idle" | "loading" | "result" | "error">("idle");
  const [checkResult, setCheckResult] = useState<{ score: number; risk: string; badge: string; factors: string[] } | null>(null);
  const [checkError, setCheckError] = useState("");
  const { user } = useAuth();

  // Fetch user's applications
  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        const { getWatchdogStatus } = await import("@/lib/api");
        const data = await getWatchdogStatus();
        const rows = Array.isArray(data)
          ? data
          : Array.isArray((data as { applications?: unknown[] }).applications)
            ? ((data as { applications?: unknown[] }).applications as Record<string, unknown>[])
            : [];
        setApps(
          rows.map((app) => {
            const row = toRecord(app) || {};
            return {
              id: String(row.application_id || row.id || ""),
              status: String(row.status || "submitted"),
              posting_status: String(row.posting_status || "unknown"),
              created_at: String(row.created_at || row.submitted_at || ""),
              submitted_at: row.submitted_at ? String(row.submitted_at) : null,
              days_since_applied:
                typeof row.days_since_applied === "number" ? row.days_since_applied : undefined,
            job: {
                title: String(row.title || "Untitled role"),
                company: String(row.company || "Unknown company"),
              ats_type: "unknown",
            },
            };
          }),
        );
      } catch { /* silent */ }
      finally { setLoadingApps(false); }
    })();
  }, [user]);

  const handleUrlCheck = useCallback(async (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setUrl(trimmed);
    setCheckState("loading");
    setCheckError("");
    setCheckResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ghost/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) throw new Error(`Check failed (${res.status})`);
      const data = await res.json();
      setCheckResult(data);
      setCheckState("result");
    } catch (err) {
      setCheckError(err instanceof Error ? err.message : "Something went wrong");
      setCheckState("error");
    }
  }, []);

  const statusColor = checkResult?.badge === "verified" ? "var(--g)" : checkResult?.badge === "ghost_risk" ? "var(--error)" : "var(--warning)";
  const statusLabel = checkResult?.badge === "verified" ? "Active" : checkResult?.badge === "ghost_risk" ? "Likely Removed" : "Uncertain";

  // Stats
  const active = apps.filter(a => a.posting_status === "active").length;
  const edited = apps.filter(a => a.posting_status === "edited").length;
  const removed = apps.filter(a => a.posting_status === "removed").length;
  const focusedApp = seed?.applicationId ? apps.find((app) => app.id === seed.applicationId) : null;
  const focusedAppContext: ApplicationContextPayload | null = focusedApp
    ? {
        application_id: focusedApp.id,
        company: focusedApp.job.company,
        role: focusedApp.job.title,
        status: focusedApp.status,
        posting_status: focusedApp.posting_status,
        submitted_at: focusedApp.submitted_at,
        days_since_applied: focusedApp.days_since_applied,
      }
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 24 }}>
      {/* URL checker */}
      <div style={{ width: "100%", maxWidth: 620, marginBottom: 8 }}>
        <SeedContextCard seed={seed} />
        <SectionLabel>Check Any Posting</SectionLabel>
        <p style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.6, marginBottom: 14 }}>
          Verify any job posting — is it still live, edited, or removed?
        </p>
        <form onSubmit={(e) => { e.preventDefault(); handleUrlCheck(url); }} style={{ display: "flex", gap: 8, width: "100%" }}>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste a job URL to check if it's still active..."
            aria-label="Job posting URL"
            className="input"
            style={{ flex: 1, padding: "12px 16px", fontSize: 14, borderRadius: 8, background: "var(--sf)", border: "1px solid var(--b)" }}
          />
          <button type="submit" disabled={checkState === "loading"} className="btn-violet" style={{ borderRadius: 8, padding: "12px 24px", fontSize: 11, letterSpacing: "0.08em", minWidth: 90 }}>
            {checkState === "loading" ? "..." : "Check"}
          </button>
        </form>
      </div>

      {checkState === "loading" && <AnalyzingState label="Checking posting status..." />}
      {checkState === "error" && checkError && (
        <div className="intel-fade-in" style={{ fontSize: 13, color: "var(--error)", fontFamily: "var(--font-body)" }}>{checkError}</div>
      )}
      {checkState === "result" && checkResult && (
        <ResultCard>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: statusColor, boxShadow: `0 0 8px ${statusColor}` }} />
            <span style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 700, color: statusColor }}>{statusLabel}</span>
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--t3)", letterSpacing: "0.08em", textTransform: "uppercase" as const, marginBottom: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{url}</div>
          {checkResult.factors.length > 0 && (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              {checkResult.factors.map((f, i) => (
                <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, color: "var(--t2)", lineHeight: 1.6, fontFamily: "var(--font-body)" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: statusColor, flexShrink: 0, marginTop: 7 }} />
                  {f}
                </li>
              ))}
            </ul>
          )}
          <button type="button" onClick={() => { setUrl(""); setCheckResult(null); setCheckState("idle"); }}
            style={{ marginTop: 16, background: "none", border: "1px solid var(--b)", borderRadius: 8, padding: "8px 16px", color: "var(--t3)", fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase" as const, cursor: "pointer", width: "100%" }}
          >Check another</button>

          <NextActionCard
            label={
              checkResult.badge === "ghost_risk"
                ? "Archive this role or stop prioritizing it"
                : checkResult.badge === "verified"
                  ? "Keep Foxhound monitoring this posting"
                  : "Watch this posting closely before following up"
            }
            detail={
              checkResult.badge === "ghost_risk"
                ? "Foxhound sees enough risk that this posting may no longer be worth your attention unless you already have recruiter traction."
                : checkResult.badge === "verified"
                  ? "The posting still looks live. Let Foxhound keep checking the page so you only act when there is a real change."
                  : "This posting is still worth tracking, but you should wait for a clearer status signal before investing more effort."
            }
          />
        </ResultCard>
      )}

      {/* Your tracked applications */}
      {user && (
        <div style={{ width: "100%", maxWidth: 620 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <SectionLabel>Your Applications</SectionLabel>
            <div style={{ display: "flex", gap: 12 }}>
              {[
                { label: "Active", count: active, color: "var(--g)" },
                { label: "Edited", count: edited, color: "var(--warning)" },
                { label: "Removed", count: removed, color: "var(--error)" },
              ].map(s => (
                <span key={s.label} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontFamily: "var(--font-mono)", fontSize: 10, color: s.color }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: s.color }} />
                  {s.count} {s.label}
                </span>
              ))}
            </div>
          </div>

          {loadingApps ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <ShimmerBlock h={48} />
              <ShimmerBlock h={48} />
              <ShimmerBlock h={48} />
            </div>
          ) : apps.length === 0 ? (
            <div style={{ padding: "32px 0", textAlign: "center", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t3)" }}>
              No applications yet. Apply to jobs to start tracking.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {apps.map(app => {
                const pColor = POSTING_COLORS[app.posting_status] || POSTING_COLORS.unknown;
                const pLabel = app.posting_status === "unknown" ? "Not checked" : app.posting_status;
                const isFocused = seed?.applicationId === app.id;
                return (
                  <div key={app.id} style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "12px 16px", background: isFocused ? "rgba(139,92,246,0.06)" : "var(--sf)", border: `1px solid ${isFocused ? "var(--bv)" : "var(--b)"}`,
                    borderRadius: 8, transition: "border-color 0.2s",
                  }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--bv)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--b)"; }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontFamily: "var(--font-body)", fontSize: 13, fontWeight: 500, color: "var(--t)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {app.job.title}
                      </div>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--t3)", marginTop: 2 }}>
                        {app.job.company}
                      </div>
                    </div>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontFamily: "var(--font-mono)", fontSize: 10, color: pColor, textTransform: "capitalize", flexShrink: 0 }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: pColor }} />
                      {pLabel}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          <NextActionCard
            label={
              focusedApp?.posting_status === "removed"
                ? "Stop investing in this role unless you already have traction"
                : focusedApp?.posting_status === "edited"
                  ? "Review the change before you follow up"
                  : "Let Foxhound keep monitoring until something changes"
            }
            detail={
              focusedApp?.posting_status === "removed"
                ? "Foxhound has a strong signal that the posting is no longer active. This is the right time to archive it and focus on stronger live opportunities."
                : focusedApp?.posting_status === "edited"
                  ? "The posting changed after you applied. Check the brief and people research before you send outreach."
                  : "Status tracking is most valuable when nothing happens for a while. Foxhound should keep checking the live posting and surface the right follow-up window."
            }
            href={seed?.applicationId ? `/brief/${seed.applicationId}` : undefined}
            hrefLabel="Open Foxhound Brief"
          />

          <ApplicationWorkflowCard context={focusedAppContext} />
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════ */

const TAB_COMPONENTS: Record<TabId, (props: { seed?: ContextSeed }) => ReactNode> = {
  ghost: GhostDetectorTab,
  brief: CompanyBriefTab,
  interview: InterviewPrepTab,
  people: PeopleResearchTab,
  discovery: JobDiscoveryTab,
  status: StatusTrackerTab,
};

export default function IntelligencePage() {
  const initialParams = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : null;
  const initialRequestedTab = initialParams?.get("tab") as TabId | null;
  const [activeTab, setActiveTab] = useState<TabId>(
    initialRequestedTab && TABS.some((tab) => tab.id === initialRequestedTab)
      ? initialRequestedTab
      : "discovery",
  );
  const { user, loading } = useAuth();
  const tabBarRef = useRef<HTMLDivElement>(null);
  const [contextCompany] = useState<string | null>(initialParams?.get("company") || null);
  const [contextRole] = useState<string | null>(initialParams?.get("role") || null);
  const [contextApplicationId] = useState<string | null>(initialParams?.get("applicationId") || null);
  const seed = useMemo<ContextSeed | undefined>(() => {
    if (!contextCompany && !contextRole && !contextApplicationId) return undefined;
    return {
      company: contextCompany || undefined,
      role: contextRole || undefined,
      applicationId: contextApplicationId || undefined,
    };
  }, [contextApplicationId, contextCompany, contextRole]);

  // Keyboard navigation for tab bar
  const handleTabKeyDown = useCallback(
    (e: React.KeyboardEvent, index: number) => {
      let nextIndex = index;
      if (e.key === "ArrowRight") {
        nextIndex = (index + 1) % TABS.length;
        e.preventDefault();
      } else if (e.key === "ArrowLeft") {
        nextIndex = (index - 1 + TABS.length) % TABS.length;
        e.preventDefault();
      } else if (e.key === "Home") {
        nextIndex = 0;
        e.preventDefault();
      } else if (e.key === "End") {
        nextIndex = TABS.length - 1;
        e.preventDefault();
      } else return;

      setActiveTab(TABS[nextIndex].id);
      const btns =
        tabBarRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
      btns?.[nextIndex]?.focus();
    },
    [setActiveTab],
  );

  const TabContent = TAB_COMPONENTS[activeTab];
  const showAppNav = !loading && !!user;

  if (loading) {
    return (
      <>
        <AppNav />
        <PageSkeleton variant="research" />
      </>
    );
  }

  return (
    <AuthGuard>
      {/* Scoped animations */}
      <style>{`
        @keyframes intel-spin {
          to { transform: rotate(360deg); }
        }
        @keyframes intel-fade-in-up {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes intel-bar-fill {
          from { width: 0; }
        }
        .intel-fade-in {
          animation: intel-fade-in-up 0.4s ease-out both;
        }
        .intel-d1 { animation-delay: 0.06s; }
        .intel-d2 { animation-delay: 0.12s; }
        .intel-d3 { animation-delay: 0.18s; }
        .intel-d4 { animation-delay: 0.24s; }

        .intel-skel {
          position: relative;
          overflow: hidden;
        }
        .intel-skel::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.04) 40%,
            rgba(255, 255, 255, 0.06) 50%,
            rgba(255, 255, 255, 0.04) 60%,
            transparent 100%
          );
          animation: intel-shimmer 1.8s ease-in-out infinite;
        }
        @keyframes intel-shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }

        /* Tab bar — equal-width tabs fill the row */
        .intel-tab-bar {
          display: flex;
          gap: 0;
          overflow-x: auto;
          scrollbar-width: none;
          -webkit-overflow-scrolling: touch;
        }
        .intel-tab-bar::-webkit-scrollbar {
          display: none;
        }

        .intel-tab {
          position: relative;
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 10px 10px 12px;
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          color: var(--t3);
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 500;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          white-space: nowrap;
          cursor: pointer;
          transition: color 0.2s, border-color 0.2s, background 0.2s;
          min-height: 44px;
          flex: 1 1 0%;
          justify-content: center;
        }
        .intel-tab:hover {
          color: var(--t2);
          background: rgba(255,255,255,0.02);
        }
        .intel-tab[aria-selected="true"] {
          color: var(--vl);
          border-bottom-color: var(--v);
          background: rgba(139,92,246,0.04);
        }
        .intel-tab:focus-visible {
          outline: 2px solid var(--v);
          outline-offset: -2px;
          border-radius: 4px 4px 0 0;
        }

        /* Helper text: hidden by default, revealed on active tab */
        .intel-tab-helper {
          display: none;
          font-size: 9px;
          color: var(--t3);
          letter-spacing: 0.06em;
          text-transform: uppercase;
          font-weight: 400;
        }
        .intel-tab[aria-selected="true"] .intel-tab-helper {
          display: block;
        }

        @media (prefers-reduced-motion: reduce) {
          .intel-fade-in { animation: none !important; opacity: 1; transform: none; }
          .intel-skel::after { animation: none; }
        }

        /* Tablet: tighten spacing, hide helpers */
        @media (max-width: 900px) {
          .intel-tab {
            padding: 10px 8px 12px;
            font-size: 9px;
            letter-spacing: 0.06em;
          }
          .intel-tab-helper {
            display: none !important;
          }
        }

        /* Mobile: scroll horizontally, fixed-size tabs */
        @media (max-width: 640px) {
          .intel-tab {
            flex: 0 0 auto;
            padding: 10px 12px;
            font-size: 9px;
            letter-spacing: 0.06em;
          }
          .intel-tab-helper {
            display: none !important;
          }
        }
      `}</style>

      {/* Nav — AppNav for logged-in, simple header for anonymous */}
      {showAppNav ? (
        <AppNav />
      ) : (
        <nav
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            zIndex: 100,
            padding: "16px 48px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "rgba(8,8,8,0.92)",
            backdropFilter: "blur(20px)",
            borderBottom: "1px solid var(--b)",
          }}
        >
          <Link
            href="/"
            style={{
              fontFamily: "var(--font-display)",
              fontWeight: 700,
              fontSize: 15,
              letterSpacing: "0.12em",
              textTransform: "uppercase" as const,
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "var(--v)",
                boxShadow: "0 0 10px var(--v), 0 0 20px rgba(139,92,246,0.25)",
              }}
            />
            Foxhound
          </Link>
          <Link href="/login" className="btn-violet">
            Sign in
          </Link>
        </nav>
      )}

      <main
        style={{
          minHeight: "100dvh",
          paddingTop: 70,
          paddingBottom: 80,
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* Ambient glow */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            top: "-5%",
            left: "30%",
            width: "min(800px, 100vw)",
            height: "min(800px, 100vw)",
            background:
              "radial-gradient(circle, rgba(139,92,246,0.08) 0%, rgba(99,102,241,0.03) 40%, transparent 60%)",
            pointerEvents: "none",
          }}
        />

        {/* Header */}
        <header
          style={{
            maxWidth: 1100,
            margin: "0 auto",
            padding: "40px var(--section-px) 0",
            position: "relative",
            zIndex: 1,
          }}
        >
          {/* Section label */}
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--v)",
              letterSpacing: "0.2em",
              textTransform: "uppercase" as const,
              marginBottom: 16,
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "var(--v)",
                boxShadow: "0 0 8px var(--v)",
                animation: "status-pulse 2.5s ease-in-out infinite",
              }}
            />
            Foxhound Research
          </div>

          {/* Heading */}
          <h1
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "clamp(28px, 5vw, 48px)",
              fontWeight: 700,
              letterSpacing: "-0.04em",
              lineHeight: 1.1,
              textTransform: "uppercase" as const,
              marginBottom: 8,
            }}
          >
            Research
          </h1>
          <p
            style={{
              fontSize: 15,
              color: "var(--t2)",
              lineHeight: 1.6,
              marginBottom: 0,
            }}
          >
            Foxhound runs this research automatically for every strong match.
            You can also run any of these yourself.
          </p>
          <div
            style={{
              marginTop: 18,
              display: "grid",
              gap: 10,
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            }}
          >
            {[
              {
                label: "Auto-runs",
                detail:
                  "Foxhound researches every strong match and every application without you asking.",
              },
              {
                label: "On-demand",
                detail:
                  "Run any of these yourself on any company or role.",
              },
              {
                label: "Linked",
                detail:
                  "Open from an application to auto-fill the company and role.",
              },
            ].map((item) => (
              <div
                key={item.label}
                style={{
                  background: "var(--sf)",
                  border: "1px solid var(--b)",
                  borderRadius: 10,
                  padding: "14px 16px",
                }}
              >
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    color: "var(--vl)",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    marginBottom: 8,
                  }}
                >
                  {item.label}
                </div>
                <div style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6 }}>
                  {item.detail}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16 }}>
            <SeedContextCard seed={seed} mode="page" />
          </div>
        </header>

        {/* Tab bar */}
        <div
          style={{
            maxWidth: 1100,
            margin: "0 auto",
            padding: "0 var(--section-px)",
            position: "relative",
            zIndex: 1,
          }}
        >
          <div
            ref={tabBarRef}
            className="intel-tab-bar"
            role="tablist"
            aria-label="Intelligence tools"
            style={{ borderBottom: "1px solid var(--b)", marginTop: 28 }}
          >
            {TABS.map((tab, i) => (
              <button
                key={tab.id}
                role="tab"
                id={`intel-tab-${tab.id}`}
                aria-selected={activeTab === tab.id}
                aria-controls={`intel-panel-${tab.id}`}
                tabIndex={activeTab === tab.id ? 0 : -1}
                className="intel-tab"
                onClick={() => setActiveTab(tab.id)}
                onKeyDown={(e) => handleTabKeyDown(e, i)}
              >
                {tab.icon}
                <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 1 }}>
                  <span>{tab.label}</span>
                  <span className="intel-tab-helper">{tab.helper}</span>
                </span>
                {tab.requiresAuth && !user && !loading && (
                  <svg
                    width="10"
                    height="10"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{ opacity: 0.5, marginLeft: 2, flexShrink: 0 }}
                  >
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                )}
              </button>
            ))}
          </div>
          {/* autoRun strip removed — users don't need to know when things run */}
        </div>

        {/* Tab panel */}
        <div
          role="tabpanel"
          id={`intel-panel-${activeTab}`}
          aria-labelledby={`intel-tab-${activeTab}`}
          style={{
            maxWidth: 1100,
            margin: "0 auto",
            padding: "32px var(--section-px) 0",
            position: "relative",
            zIndex: 1,
          }}
        >
          <TabContent seed={seed} />
        </div>

        {/* Footer */}
        <footer
          style={{
            marginTop: 80,
            textAlign: "center",
            position: "relative",
            zIndex: 1,
          }}
        >
          <p
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--t3)",
              letterSpacing: "0.08em",
              textTransform: "uppercase" as const,
              lineHeight: 1.8,
            }}
          >
            Powered by{" "}
            <Link
              href="/"
              style={{
                color: "var(--vl)",
                borderBottom: "1px solid rgba(139,92,246,0.2)",
              }}
            >
              Foxhound
            </Link>
          </p>
        </footer>
      </main>
    </AuthGuard>
  );
}
