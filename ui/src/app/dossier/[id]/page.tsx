'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import AppNav from '@/components/AppNav';
import { getDossier } from '@/lib/api';

/* ═══════════════════════════════════════
   Types
   ═══════════════════════════════════════ */

interface NewsItem {
  title: string;
  source: string;
  date: string;
  url?: string;
}

interface TeamContact {
  name: string;
  title: string;
  department?: string;
  linkedin_search_url?: string;
}

interface OutreachDraft {
  linkedin_message: string;
  email_draft: string;
}

interface InterviewProcess {
  stages: string[];
  timeline: string;
  tips: string[];
  common_questions: string[];
  difficulty: string;
}

interface SalaryEstimate {
  range: string;
  total_comp: string;
  median: string;
  source: string;
  by_level?: { level: string; total_comp: string }[];
}

interface InterviewPrep {
  key_themes: string[];
  likely_questions: string[];
  talking_points?: string[];
  technical_focus?: string[];
}

interface InstantAnalysis {
  insider_tip: string;
  tech_stack: string[];
  role_analysis?: string;
}

interface CompanyData {
  mission?: string;
  founded?: string;
  size?: string;
  locations?: string[];
  funding?: string;
  products?: string[];
}

interface CareersData {
  open_roles?: number;
  top_departments?: string[];
  hiring_velocity?: string;
  growth_signals?: string;
}

interface DossierData {
  id: string;
  application_id: string;
  company_normalized: string;
  status: 'building' | 'partial' | 'ready' | 'failed';
  instant_analysis: InstantAnalysis | null;
  company_data: CompanyData | null;
  careers_data: CareersData | null;
  news_data: NewsItem[] | null;
  team_contacts: TeamContact[] | null;
  outreach_draft: OutreachDraft | null;
  interview_prep: InterviewPrep | null;
  interview_process: InterviewProcess | null;
  culture_report: string | null;
  executive_summary: string | null;
  salary_estimate: SalaryEstimate | null;
  levels_fyi_data: Record<string, unknown> | null;
  reddit_interviews_data: Record<string, unknown> | null;
  reddit_culture_data: Record<string, unknown> | null;
  engineering_blog_data: Record<string, unknown> | null;
  overall_assessment: string | null;
  sources_completed: string[];
  sources_failed: string[];
  created_at: string;
  completed_at: string | null;
  company_name?: string;
  role_title?: string;
}

/* ═══════════════════════════════════════
   Tab definitions
   ═══════════════════════════════════════ */

type TabKey = 'overview' | 'interview' | 'outreach' | 'compensation';

const TAB_META: { key: TabKey; label: string; shortLabel: string }[] = [
  { key: 'overview', label: 'Overview', shortLabel: 'Overview' },
  { key: 'interview', label: 'Interview Intel', shortLabel: 'Interview' },
  { key: 'outreach', label: 'Outreach', shortLabel: 'Outreach' },
  { key: 'compensation', label: 'Compensation', shortLabel: 'Comp' },
];

/* ═══════════════════════════════════════
   Primitives (ReconCard-matched styling)
   ═══════════════════════════════════════ */

/** Monospace micro-label used for section headers */
function MicroLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 500,
        color: 'var(--vl)',
        letterSpacing: '0.15em',
        textTransform: 'uppercase',
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

/** Sub-label for subsections within a tab */
function SubLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 9,
        color: 'var(--t3)',
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        marginBottom: 8,
      }}
    >
      {children}
    </div>
  );
}

/** Body text matching ReconCard prose */
function Prose({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 13,
        fontFamily: 'var(--font-body)',
        color: 'var(--t2)',
        lineHeight: 1.65,
      }}
    >
      {children}
    </div>
  );
}

/** Render a value that might be structured data OR a raw text string/object */
/** Render a single line with basic markdown: **bold**, *italic*, `code` */
function renderMarkdownLine(line: string) {
  const parts: React.ReactNode[] = [];
  const remaining = line;
  let idx = 0;

  // Process **bold**, *italic*, `code`
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let match: RegExpExecArray | null;
  let lastIndex = 0;

  while ((match = regex.exec(remaining)) !== null) {
    if (match.index > lastIndex) {
      parts.push(remaining.slice(lastIndex, match.index));
    }
    if (match[2]) {
      parts.push(<strong key={idx++} style={{ color: 'var(--t)', fontWeight: 600 }}>{match[2]}</strong>);
    } else if (match[3]) {
      parts.push(<em key={idx++}>{match[3]}</em>);
    } else if (match[4]) {
      parts.push(
        <code key={idx++} style={{
          fontFamily: 'var(--font-mono)', fontSize: '0.9em',
          background: 'var(--sf)', padding: '1px 5px', borderRadius: 3,
        }}>{match[4]}</code>
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < remaining.length) {
    parts.push(remaining.slice(lastIndex));
  }

  return parts.length > 0 ? <>{parts}</> : <>{line}</>;
}

/** Render text with markdown support: headings, bold, bullets, paragraphs */
function SmartProse({ data, maxLines }: { data: unknown; maxLines?: number }) {
  if (!data) return null;

  // Unwrap {result: "..."} wrapper
  let text: string | null = null;
  if (typeof data === 'object' && data !== null && 'result' in data) {
    const r = (data as { result: unknown }).result;
    if (typeof r === 'string') text = r;
  }
  if (typeof data === 'string') text = data;
  if (!text) return null;

  // Split into lines
  let lines = text.split('\n').filter((l) => l.trim() !== '');
  if (maxLines && lines.length > maxLines) {
    lines = lines.slice(0, maxLines);
  }

  const elements: React.ReactNode[] = [];
  let listItems: React.ReactNode[] = [];

  const flushList = () => {
    if (listItems.length > 0) {
      elements.push(
        <ul key={`ul-${elements.length}`} style={{
          margin: '6px 0', paddingLeft: 18, listStyle: 'none',
          display: 'flex', flexDirection: 'column', gap: 4,
        }}>
          {listItems.map((li, j) => (
            <li key={j} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
              <span style={{ color: 'var(--v)', fontSize: 8, flexShrink: 0, marginTop: 4 }}>&#9679;</span>
              <span>{li}</span>
            </li>
          ))}
        </ul>
      );
      listItems = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    // Headings: ### or **Heading**
    if (line.startsWith('### ') || line.startsWith('## ') || line.startsWith('# ')) {
      flushList();
      const heading = line.replace(/^#+\s*/, '').replace(/\*\*/g, '');
      elements.push(
        <div key={i} style={{
          fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 600,
          color: 'var(--t)', marginTop: elements.length > 0 ? 12 : 0, marginBottom: 4,
        }}>
          {heading}
        </div>
      );
      continue;
    }

    // Standalone bold line as section header (e.g. **Mission**)
    if (/^\*\*[^*]+\*\*$/.test(line)) {
      flushList();
      const heading = line.replace(/\*\*/g, '');
      elements.push(
        <div key={i} style={{
          fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 600,
          color: 'var(--t)', marginTop: elements.length > 0 ? 10 : 0, marginBottom: 2,
        }}>
          {heading}
        </div>
      );
      continue;
    }

    // Bold key: value line (e.g. **Founding Year** 2019)
    const kvMatch = line.match(/^\*\*(.+?)\*\*\s*(.+)/);
    if (kvMatch) {
      flushList();
      elements.push(
        <div key={i} style={{ marginBottom: 4 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            {kvMatch[1]}
          </span>
          <div style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--t)', marginTop: 1 }}>
            {renderMarkdownLine(kvMatch[2])}
          </div>
        </div>
      );
      continue;
    }

    // Bullet points: - or *
    if (/^[-*]\s+/.test(line)) {
      const content = line.replace(/^[-*]\s+/, '');
      listItems.push(renderMarkdownLine(content));
      continue;
    }

    // Table rows: | ... | — skip header separators
    if (line.startsWith('|') && line.includes('---')) continue;
    if (line.startsWith('|')) {
      flushList();
      const cells = line.split('|').filter(Boolean).map(c => c.trim());
      elements.push(
        <div key={i} style={{
          display: 'flex', gap: 16, padding: '4px 0',
          borderBottom: '1px solid var(--b)', fontSize: 12,
        }}>
          {cells.map((cell, ci) => (
            <span key={ci} style={{
              flex: ci === 0 ? '0 0 140px' : 1,
              fontWeight: ci === 0 ? 600 : 400,
              fontFamily: ci === 0 ? 'var(--font-mono)' : 'var(--font-body)',
              fontSize: ci === 0 ? 10 : 12,
              color: ci === 0 ? 'var(--t3)' : 'var(--t2)',
            }}>
              {renderMarkdownLine(cell)}
            </span>
          ))}
        </div>
      );
      continue;
    }

    // Regular paragraph
    flushList();
    elements.push(
      <p key={i} style={{ marginBottom: 6, marginTop: 0 }}>
        {renderMarkdownLine(line)}
      </p>
    );
  }

  flushList();

  return <Prose>{elements}</Prose>;
}

function DataPoint({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          color: 'var(--t3)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
          color: 'var(--t)',
          fontWeight: 500,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function TechPill({ name }: { name: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        fontWeight: 500,
        color: 'var(--vl)',
        background: 'var(--vf)',
        border: '1px solid var(--bv)',
        borderRadius: 4,
        padding: '3px 8px',
        letterSpacing: '0.02em',
      }}
    >
      {name}
    </span>
  );
}

function DifficultyBadge({ level }: { level: string }) {
  const normalized = level.toLowerCase();
  const colorMap: Record<string, { bg: string; text: string; border: string }> = {
    easy: { bg: 'rgba(52,211,153,0.08)', text: 'var(--g)', border: 'rgba(52,211,153,0.2)' },
    medium: { bg: 'rgba(251,191,36,0.08)', text: 'var(--warning)', border: 'rgba(251,191,36,0.2)' },
    hard: { bg: 'rgba(248,113,113,0.08)', text: 'var(--error)', border: 'rgba(248,113,113,0.2)' },
  };
  const colors = colorMap[normalized] || colorMap.medium;

  return (
    <span
      style={{
        display: 'inline-block',
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        color: colors.text,
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        borderRadius: 4,
        padding: '2px 8px',
      }}
    >
      {level}
    </span>
  );
}

function InterviewPipeline({ stages }: { stages: string[] }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 0,
        margin: '8px 0 12px',
      }}
    >
      {stages.map((stage, i) => (
        <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              width: '100%',
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: 'var(--v)',
                flexShrink: 0,
                marginTop: 5,
              }}
            />
            <span
              style={{
                fontFamily: 'var(--font-body)',
                fontSize: 13,
                color: 'var(--t)',
                lineHeight: 1.5,
              }}
            >
              {stage}
            </span>
          </div>
          {i < stages.length - 1 && (
            <div
              aria-hidden="true"
              style={{
                marginLeft: 8,
                width: 1,
                height: 16,
                background: 'rgba(139, 92, 246, 0.2)',
              }}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function QuoteBlock({ children }: { children: React.ReactNode }) {
  return (
    <blockquote
      style={{
        borderLeft: '2px solid var(--bv)',
        paddingLeft: 12,
        margin: '6px 0',
        fontStyle: 'italic',
        color: 'var(--t2)',
        fontSize: 13,
        lineHeight: 1.6,
        fontFamily: 'var(--font-body)',
      }}
    >
      {children}
    </blockquote>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* Clipboard API not available */
    }
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      aria-label={copied ? 'Copied to clipboard' : 'Copy to clipboard'}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        padding: '4px 10px',
        borderRadius: 4,
        cursor: 'pointer',
        border: `1px solid ${copied ? 'rgba(52, 211, 153, 0.3)' : 'var(--b)'}`,
        background: copied ? 'rgba(52, 211, 153, 0.08)' : 'transparent',
        color: copied ? 'var(--g)' : 'var(--t3)',
        transition: 'all 0.2s',
        minHeight: 26,
      }}
      onMouseEnter={(e) => {
        if (!copied) {
          e.currentTarget.style.borderColor = 'var(--bv)';
          e.currentTarget.style.color = 'var(--vl)';
        }
      }}
      onMouseLeave={(e) => {
        if (!copied) {
          e.currentTarget.style.borderColor = 'var(--b)';
          e.currentTarget.style.color = 'var(--t3)';
        }
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

/** Gradient divider matching ReconCard */
function Divider() {
  return (
    <div
      aria-hidden="true"
      style={{
        height: 1,
        background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.12), transparent)',
      }}
    />
  );
}

/** Returns true if a section has renderable data (not null, not empty array, not empty string) */
function hasData(data: unknown): boolean {
  if (data === null || data === undefined) return false;
  if (typeof data === 'string') return data.trim().length > 0;
  if (Array.isArray(data)) return data.length > 0;
  if (typeof data === 'object') {
    // Check {result: "..."} wrapper
    if ('result' in data) return hasData((data as { result: unknown }).result);
    return Object.keys(data).length > 0;
  }
  return true;
}

/* ═══════════════════════════════════════
   Shimmer skeleton
   ═══════════════════════════════════════ */

function ShimmerBlock({ w, h }: { w?: string | number; h: number }) {
  return (
    <div
      className="dossier-skel"
      style={{
        width: w ?? '100%',
        height: h,
        borderRadius: 4,
        background: 'var(--sf)',
        position: 'relative',
        overflow: 'hidden',
      }}
    />
  );
}

function SectionShimmer() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '4px 0' }}>
      <ShimmerBlock h={12} w="85%" />
      <ShimmerBlock h={12} w="65%" />
      <ShimmerBlock h={12} w="75%" />
    </div>
  );
}

/* ═══════════════════════════════════════
   Progress Bar
   ═══════════════════════════════════════ */

function ProgressBar({ completed, total }: { completed: number; total: number }) {
  const pct = total > 0 ? (completed / total) * 100 : 0;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div
        style={{
          flex: 1,
          height: 2,
          borderRadius: 1,
          background: 'var(--b)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            borderRadius: 1,
            background:
              pct === 100
                ? 'var(--g)'
                : 'linear-gradient(90deg, var(--v), var(--vl))',
            width: `${pct}%`,
            transition: 'width 0.6s ease-out, background 0.3s',
          }}
        />
      </div>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: pct === 100 ? 'var(--g)' : 'var(--t3)',
          letterSpacing: '0.04em',
          whiteSpace: 'nowrap',
        }}
      >
        {completed}/{total} sources
      </span>
    </div>
  );
}

/* ═══════════════════════════════════════
   Full-page skeleton
   ═══════════════════════════════════════ */

function DossierSkeleton() {
  return (
    <main
      className="dossier-page"
      style={{
        maxWidth: 860,
        margin: '0 auto',
        padding: '80px 20px 140px',
        position: 'relative',
        zIndex: 1,
      }}
    >
      <ShimmerBlock h={10} w={100} />
      <div style={{ height: 24 }} />
      <ShimmerBlock h={10} w={140} />
      <div style={{ height: 10 }} />
      <ShimmerBlock h={26} w={300} />
      <div style={{ height: 8 }} />
      <ShimmerBlock h={14} w={200} />
      <div style={{ height: 24 }} />

      {/* Stat pills */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {[100, 80, 120, 90].map((w, i) => (
          <ShimmerBlock key={i} h={48} w={w} />
        ))}
      </div>

      <div style={{ height: 24 }} />

      {/* Tab bar skeleton */}
      <div style={{ display: 'flex', gap: 0 }}>
        {[80, 100, 70, 90].map((w, i) => (
          <ShimmerBlock key={i} h={36} w={w} />
        ))}
      </div>

      <div style={{ height: 24 }} />

      {/* Content blocks */}
      {[0, 1, 2].map((i) => (
        <div key={i} style={{ marginBottom: 20 }}>
          <ShimmerBlock h={10} w={120} />
          <div style={{ height: 10 }} />
          <ShimmerBlock h={12} w="90%" />
          <div style={{ height: 6 }} />
          <ShimmerBlock h={12} w="75%" />
          <div style={{ height: 6 }} />
          <ShimmerBlock h={12} w="80%" />
        </div>
      ))}

      <style>{`
        .dossier-skel {
          position: relative;
          overflow: hidden;
        }
        .dossier-skel::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.04) 40%, rgba(255,255,255,0.06) 50%, rgba(255,255,255,0.04) 60%, transparent 100%);
          animation: dossier-shimmer 1.8s ease-in-out infinite;
        }
        @keyframes dossier-shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
        @media (prefers-reduced-motion: reduce) {
          .dossier-skel::after { animation: none; }
        }
      `}</style>
    </main>
  );
}

/* ═══════════════════════════════════════
   Key Stat Pill (header row)
   ═══════════════════════════════════════ */

function StatPill({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent?: boolean;
}) {
  return (
    <div
      style={{
        background: accent ? 'var(--vf)' : 'var(--sf)',
        border: `1px solid ${accent ? 'var(--bv)' : 'var(--b)'}`,
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 0,
        flex: '0 1 auto',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          color: 'var(--t3)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          marginBottom: 4,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 14,
          fontWeight: 600,
          color: accent ? 'var(--vl)' : 'var(--t)',
          letterSpacing: '-0.01em',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {value}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════
   Tab Bar
   ═══════════════════════════════════════ */

function TabBar({
  tabs,
  activeTab,
  onTabChange,
  tabHasContent,
}: {
  tabs: typeof TAB_META;
  activeTab: TabKey;
  onTabChange: (tab: TabKey) => void;
  tabHasContent: Record<TabKey, boolean>;
}) {
  return (
    <div
      role="tablist"
      aria-label="Report sections"
      style={{
        display: 'flex',
        gap: 0,
        borderBottom: '1px solid var(--b)',
        overflowX: 'auto',
        scrollbarWidth: 'none',
      }}
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.key;
        const hasContent = tabHasContent[tab.key];

        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            aria-controls={`panel-${tab.key}`}
            onClick={() => onTabChange(tab.key)}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              fontWeight: isActive ? 600 : 400,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: isActive ? 'var(--t)' : hasContent ? 'var(--t3)' : 'rgba(240,240,240,0.2)',
              background: 'transparent',
              border: 'none',
              borderBottom: isActive
                ? '2px solid var(--v)'
                : '2px solid transparent',
              padding: '10px 16px',
              cursor: hasContent ? 'pointer' : 'default',
              transition: 'color 0.2s, border-color 0.2s',
              whiteSpace: 'nowrap',
              flexShrink: 0,
              opacity: hasContent ? 1 : 0.5,
            }}
            onMouseEnter={(e) => {
              if (!isActive && hasContent) {
                e.currentTarget.style.color = 'var(--t2)';
              }
            }}
            onMouseLeave={(e) => {
              if (!isActive && hasContent) {
                e.currentTarget.style.color = 'var(--t3)';
              }
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════
   Tab Panel Wrapper
   ═══════════════════════════════════════ */

function TabPanel({
  id,
  active,
  children,
}: {
  id: string;
  active: boolean;
  children: React.ReactNode;
}) {
  if (!active) return null;

  return (
    <div
      role="tabpanel"
      id={`panel-${id}`}
      aria-labelledby={id}
      style={{
        paddingTop: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 20,
        animation: 'dossier-fadein 0.2s ease-out',
      }}
    >
      {children}
    </div>
  );
}

/* ═══════════════════════════════════════
   Section Block (within a tab)
   ═══════════════════════════════════════ */

function IntelSection({
  label,
  index,
  isBuilding,
  hasContent,
  children,
}: {
  label: string;
  index: string;
  isBuilding: boolean;
  hasContent: boolean;
  children: React.ReactNode;
}) {
  // Hide entirely when report is done and no data
  if (!hasContent && !isBuilding) return null;

  const padded = index.padStart(2, '0');

  return (
    <div>
      <MicroLabel>
        {padded} / {label}
      </MicroLabel>
      {!hasContent && isBuilding ? <SectionShimmer /> : children}
    </div>
  );
}

/* ═══════════════════════════════════════
   Velocity helpers
   ═══════════════════════════════════════ */

const velocityColors: Record<string, string> = {
  growing: 'var(--g)',
  stable: 'var(--t3)',
  slowing: 'var(--error)',
};

const velocityArrows: Record<string, string> = {
  growing: '\u2191',
  stable: '\u2192',
  slowing: '\u2193',
};

/* ═══════════════════════════════════════
   Main Page
   ═══════════════════════════════════════ */

export default function DossierPage() {
  const params = useParams();
  const dossierId = params.id as string;

  const [dossier, setDossier] = useState<DossierData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDossier = useCallback(async () => {
    try {
      const data = await getDossier(dossierId);
      setDossier(data as unknown as DossierData);
      setError(null);

      if (data.status === 'ready' || data.status === 'failed') {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }
    } catch {
      if (loading) {
        setError('Report not found');
      }
    } finally {
      setLoading(false);
    }
  }, [dossierId, loading]);

  useEffect(() => {
    fetchDossier();
    pollingRef.current = setInterval(fetchDossier, 5000);
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [fetchDossier]);

  /* --- Loading --- */
  if (loading) {
    return (
      <AuthGuard>
        <AppNav />
        <DossierSkeleton />
      </AuthGuard>
    );
  }

  /* --- Error --- */
  if (error || !dossier) {
    return (
      <AuthGuard>
        <AppNav />
        <main
          style={{
            maxWidth: 860,
            margin: '0 auto',
            padding: '80px 20px 140px',
            position: 'relative',
            zIndex: 1,
            textAlign: 'center',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--t3)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              marginBottom: 16,
            }}
          >
            {error || 'Report not found'}
          </div>
          <Link
            href="/applications"
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 14,
              fontWeight: 500,
              padding: '12px 28px',
              borderRadius: 8,
              display: 'inline-flex',
              border: '1px solid rgba(255,255,255,0.1)',
              color: 'var(--t2)',
              textDecoration: 'none',
              transition: 'all 0.2s',
            }}
          >
            Back to Applications
          </Link>
        </main>
      </AuthGuard>
    );
  }

  /* ─── Derived data ─── */
  const rawName = dossier.company_name || dossier.company_normalized || 'Company';
  const companyName = rawName.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase());
  const roleTitle = dossier.role_title || '';
  const isBuilding = dossier.status === 'building' || dossier.status === 'partial';
  const failed = dossier.sources_failed || [];
  const completed = dossier.sources_completed || [];
  const totalSources = completed.length + failed.length + (isBuilding ? 2 : 0);
  const completedSources = completed.length;

  // Team contacts — normalize {contacts: [...]} vs bare array
  const teamContacts: TeamContact[] = (() => {
    if (Array.isArray(dossier.team_contacts)) return dossier.team_contacts;
    if (dossier.team_contacts && typeof dossier.team_contacts === 'object') {
      const raw = dossier.team_contacts as unknown as { contacts?: TeamContact[] };
      if (Array.isArray(raw.contacts)) return raw.contacts;
    }
    return [];
  })();

  // Salary
  const salary: SalaryEstimate | null =
    dossier.salary_estimate ||
    (dossier.levels_fyi_data
      ? {
          range: String(dossier.levels_fyi_data.range || ''),
          total_comp: String(dossier.levels_fyi_data.total_comp || ''),
          median: String(dossier.levels_fyi_data.median || ''),
          source: 'levels.fyi',
          by_level: dossier.levels_fyi_data.by_level as SalaryEstimate['by_level'],
        }
      : null);

  // Culture text extraction
  const cultureText = (() => {
    if (typeof dossier.culture_report === 'string' && dossier.culture_report.trim())
      return dossier.culture_report;
    const raw = dossier.reddit_culture_data;
    if (raw && typeof raw === 'object') {
      // Handle {result: "..."} wrapper
      if ('result' in raw && typeof (raw as Record<string, unknown>).result === 'string')
        return (raw as Record<string, unknown>).result as string;
      const parts = ['summary', 'work_life_balance', 'management', 'culture', 'growth', 'pros', 'cons']
        .map((k) => (raw as Record<string, unknown>)[k])
        .filter((v): v is string => typeof v === 'string' && v.length > 0);
      if (parts.length > 0) return parts.join('\n\n');
    }
    return null;
  })();

  // Executive summary text
  const execText = dossier.executive_summary || dossier.overall_assessment || null;

  /* ─── Determine which tabs have content ─── */
  const tabHasContent: Record<TabKey, boolean> = {
    overview:
      hasData(execText) ||
      hasData(dossier.company_data) ||
      hasData(dossier.careers_data) ||
      hasData(dossier.instant_analysis) ||
      isBuilding,
    interview:
      hasData(dossier.interview_process) ||
      hasData(cultureText) ||
      hasData(dossier.interview_prep) ||
      isBuilding,
    outreach:
      hasData(teamContacts) ||
      hasData(dossier.outreach_draft) ||
      isBuilding,
    compensation:
      hasData(salary) ||
      hasData(dossier.news_data) ||
      isBuilding,
  };

  // If active tab has no content, auto-switch to first tab that does
  const resolvedTab = tabHasContent[activeTab]
    ? activeTab
    : (TAB_META.find((t) => tabHasContent[t.key])?.key ?? 'overview');

  /* ─── Key stats for the header row ─── */
  const stats: { label: string; value: string | number; accent?: boolean }[] = [];

  if (dossier.company_data?.size) {
    stats.push({ label: 'Size', value: dossier.company_data.size });
  }
  if (dossier.careers_data?.open_roles != null) {
    stats.push({ label: 'Open Roles', value: dossier.careers_data.open_roles });
  }
  if (dossier.careers_data?.hiring_velocity) {
    const v = dossier.careers_data.hiring_velocity;
    const arrow = velocityArrows[v] || '';
    stats.push({ label: 'Velocity', value: `${arrow} ${v}` });
  }
  if (salary?.range) {
    stats.push({ label: 'Salary Range', value: salary.range, accent: true });
  } else if (salary?.total_comp) {
    stats.push({ label: 'Total Comp', value: salary.total_comp, accent: true });
  }
  if (dossier.company_data?.funding) {
    stats.push({ label: 'Funding', value: dossier.company_data.funding });
  }

  return (
    <AuthGuard>
      <AppNav />
      <main
        className="dossier-page"
        style={{
          maxWidth: 860,
          margin: '0 auto',
          padding: '80px 20px 100px',
          position: 'relative',
          zIndex: 1,
        }}
      >
        {/* ═══════════════════════════════════
            HEADER
            ═══════════════════════════════════ */}
        <section>
          {/* Back link */}
          <Link
            href="/applications"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: 'var(--t3)',
              textDecoration: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              marginBottom: 24,
              transition: 'color 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--vl)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--t3)';
            }}
          >
            <span aria-hidden="true">&larr;</span> Applications
          </Link>

          {/* Top row: label + status */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              marginBottom: 8,
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                fontWeight: 500,
                color: 'var(--vl)',
                letterSpacing: '0.15em',
                textTransform: 'uppercase',
              }}
            >
              Intelligence Report
            </span>
            {isBuilding && (
              <span
                className="dossier-pulse"
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--v)',
                  display: 'inline-block',
                }}
              />
            )}
          </div>

          {/* Company Name */}
          <h1
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 24,
              fontWeight: 700,
              letterSpacing: '-0.02em',
              color: 'var(--t)',
              margin: 0,
              lineHeight: 1.2,
              textTransform: 'uppercase',
            }}
          >
            {companyName}
          </h1>

          {/* Role + meta */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginTop: 6,
              flexWrap: 'wrap',
            }}
          >
            {roleTitle && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--t3)',
                  letterSpacing: '0.04em',
                }}
              >
                {roleTitle}
              </span>
            )}
            {dossier.created_at && (
              <>
                {roleTitle && (
                  <span style={{ color: 'var(--t3)', fontSize: 10 }} aria-hidden="true">
                    /
                  </span>
                )}
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    color: 'var(--t3)',
                    letterSpacing: '0.04em',
                  }}
                >
                  {new Date(dossier.created_at).toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                  })}
                </span>
              </>
            )}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--t3)',
                letterSpacing: '0.04em',
              }}
            >
              {completedSources} source{completedSources !== 1 ? 's' : ''}
            </span>
          </div>

          {/* Progress bar (only while building) */}
          {isBuilding && (
            <div style={{ marginTop: 14 }}>
              <ProgressBar completed={completedSources} total={Math.max(totalSources, 1)} />
            </div>
          )}
        </section>

        {/* ═══════════════════════════════════
            KEY STATS ROW
            ═══════════════════════════════════ */}
        {stats.length > 0 && (
          <div
            style={{
              display: 'flex',
              gap: 8,
              flexWrap: 'wrap',
              marginTop: 20,
            }}
          >
            {stats.map((s, i) => (
              <StatPill key={i} label={s.label} value={s.value} accent={s.accent} />
            ))}
          </div>
        )}

        {/* ═══════════════════════════════════
            TAB BAR
            ═══════════════════════════════════ */}
        <div style={{ marginTop: 24 }}>
          <TabBar
            tabs={TAB_META}
            activeTab={resolvedTab}
            onTabChange={setActiveTab}
            tabHasContent={tabHasContent}
          />
        </div>

        {/* ═══════════════════════════════════
            TAB: OVERVIEW
            ═══════════════════════════════════ */}
        <TabPanel id="overview" active={resolvedTab === 'overview'}>
          {/* Executive Summary */}
          <IntelSection
            label="Executive Summary"
            index="1"
            isBuilding={isBuilding}
            hasContent={hasData(execText)}
          >
            <div
              style={{
                borderLeft: '3px solid var(--v)',
                paddingLeft: 16,
              }}
            >
              <SmartProse data={execText} />
            </div>
          </IntelSection>

          {/* Insider Tip */}
          <IntelSection
            label="Insider Tip"
            index="2"
            isBuilding={isBuilding}
            hasContent={hasData(dossier.instant_analysis?.insider_tip)}
          >
            <div
              style={{
                background: 'rgba(139, 92, 246, 0.04)',
                border: '1px solid rgba(139, 92, 246, 0.1)',
                borderRadius: 8,
                padding: 14,
              }}
            >
              <Prose>
                <p>{dossier.instant_analysis?.insider_tip}</p>
              </Prose>
            </div>

            {dossier.instant_analysis?.tech_stack &&
              dossier.instant_analysis.tech_stack.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
                  {dossier.instant_analysis.tech_stack.map((t) => (
                    <TechPill key={t} name={t} />
                  ))}
                </div>
              )}
          </IntelSection>

          {/* Company Overview */}
          <IntelSection
            label="Company"
            index="3"
            isBuilding={isBuilding}
            hasContent={hasData(dossier.company_data)}
          >
            {dossier.company_data && typeof dossier.company_data === 'string' ? (
              <SmartProse data={dossier.company_data} />
            ) : dossier.company_data && typeof dossier.company_data === 'object' ? (
              <>
                {dossier.company_data.mission && (
                  <div style={{ marginBottom: 14 }}>
                    <SmartProse data={dossier.company_data.mission} />
                  </div>
                )}
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
                    gap: '10px 20px',
                  }}
                >
                  {dossier.company_data.founded && (
                    <DataPoint label="Founded" value={dossier.company_data.founded} />
                  )}
                  {dossier.company_data.size && (
                    <DataPoint label="Size" value={dossier.company_data.size} />
                  )}
                  {dossier.company_data.funding && (
                    <DataPoint label="Funding" value={dossier.company_data.funding} />
                  )}
                  {dossier.company_data.locations &&
                    dossier.company_data.locations.length > 0 && (
                      <DataPoint
                        label="Locations"
                        value={dossier.company_data.locations.slice(0, 3).join(', ')}
                      />
                    )}
                </div>
                {dossier.company_data.products &&
                  dossier.company_data.products.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <SubLabel>Products</SubLabel>
                      <Prose>
                        <p>{dossier.company_data.products.join(' \u00B7 ')}</p>
                      </Prose>
                    </div>
                  )}
              </>
            ) : null}
          </IntelSection>

          {/* Hiring Velocity */}
          <IntelSection
            label="Hiring Velocity"
            index="4"
            isBuilding={isBuilding}
            hasContent={hasData(dossier.careers_data)}
          >
            {dossier.careers_data && typeof dossier.careers_data === 'string' ? (
              <SmartProse data={dossier.careers_data} maxLines={25} />
            ) : dossier.careers_data && typeof dossier.careers_data === 'object' ? (
              <>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: 12,
                    marginBottom: 10,
                    flexWrap: 'wrap',
                  }}
                >
                  {dossier.careers_data.open_roles != null && (
                    <>
                      <span
                        style={{
                          fontFamily: 'var(--font-display)',
                          fontSize: 28,
                          fontWeight: 700,
                          color: 'var(--t)',
                          letterSpacing: '-0.03em',
                          lineHeight: 1,
                        }}
                      >
                        {dossier.careers_data.open_roles}
                      </span>
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 11,
                          color: 'var(--t3)',
                          letterSpacing: '0.04em',
                        }}
                      >
                        open roles
                      </span>
                    </>
                  )}
                  {dossier.careers_data.hiring_velocity && (
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 12,
                        fontWeight: 600,
                        color:
                          velocityColors[dossier.careers_data.hiring_velocity] || 'var(--t3)',
                      }}
                    >
                      {velocityArrows[dossier.careers_data.hiring_velocity] || ''}{' '}
                      {dossier.careers_data.hiring_velocity}
                    </span>
                  )}
                </div>

                {dossier.careers_data.top_departments &&
                  dossier.careers_data.top_departments.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <SubLabel>Top Departments</SubLabel>
                      <Prose>
                        <p>{dossier.careers_data.top_departments.join(', ')}</p>
                      </Prose>
                    </div>
                  )}

                {dossier.careers_data.growth_signals && (
                  <SmartProse data={dossier.careers_data.growth_signals} />
                )}
              </>
            ) : null}
          </IntelSection>
        </TabPanel>

        {/* ═══════════════════════════════════
            TAB: INTERVIEW INTEL
            ═══════════════════════════════════ */}
        <TabPanel id="interview" active={resolvedTab === 'interview'}>
          {/* Interview Process */}
          <IntelSection
            label="Interview Process"
            index="1"
            isBuilding={isBuilding}
            hasContent={hasData(dossier.interview_process)}
          >
            {dossier.interview_process && (
              <>
                {/* Check if interview_process is a raw text string */}
                {typeof dossier.interview_process === 'string' ? (
                  <SmartProse data={dossier.interview_process} />
                ) : (
                  <>
                    {dossier.interview_process.stages &&
                      dossier.interview_process.stages.length > 0 && (
                        <InterviewPipeline stages={dossier.interview_process.stages} />
                      )}

                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        marginBottom: 14,
                        flexWrap: 'wrap',
                      }}
                    >
                      {dossier.interview_process.timeline && (
                        <span
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: 11,
                            color: 'var(--t2)',
                          }}
                        >
                          Timeline: {dossier.interview_process.timeline}
                        </span>
                      )}
                      {dossier.interview_process.difficulty && (
                        <DifficultyBadge level={dossier.interview_process.difficulty} />
                      )}
                    </div>

                    {dossier.interview_process.common_questions &&
                      dossier.interview_process.common_questions.length > 0 && (
                        <div style={{ marginBottom: 14 }}>
                          <SubLabel>Common Questions</SubLabel>
                          {dossier.interview_process.common_questions.map((q, i) => (
                            <QuoteBlock key={i}>{q}</QuoteBlock>
                          ))}
                        </div>
                      )}

                    {dossier.interview_process.tips &&
                      dossier.interview_process.tips.length > 0 && (
                        <div>
                          <SubLabel>Tips</SubLabel>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {dossier.interview_process.tips.map((tip, i) => (
                              <div
                                key={i}
                                style={{
                                  display: 'flex',
                                  gap: 8,
                                  alignItems: 'baseline',
                                  fontSize: 13,
                                  color: 'var(--t2)',
                                  lineHeight: 1.6,
                                  fontFamily: 'var(--font-body)',
                                }}
                              >
                                <span
                                  style={{
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: 10,
                                    color: 'var(--vl)',
                                    fontWeight: 600,
                                    flexShrink: 0,
                                    minWidth: 14,
                                  }}
                                >
                                  {i + 1}.
                                </span>
                                {tip}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                  </>
                )}
              </>
            )}
          </IntelSection>

          {/* Culture & Work Life */}
          <IntelSection
            label="Culture & Work Life"
            index="2"
            isBuilding={isBuilding}
            hasContent={hasData(cultureText)}
          >
            <SmartProse data={cultureText} />
          </IntelSection>

          {/* Interview Prep */}
          <IntelSection
            label="Interview Prep"
            index="3"
            isBuilding={isBuilding}
            hasContent={hasData(dossier.interview_prep)}
          >
            {dossier.interview_prep && (
              <>
                {/* Check if it is raw text */}
                {typeof dossier.interview_prep === 'string' ? (
                  <SmartProse data={dossier.interview_prep} />
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    {dossier.interview_prep.key_themes &&
                      dossier.interview_prep.key_themes.length > 0 && (
                        <div>
                          <SubLabel>Key Themes</SubLabel>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {dossier.interview_prep.key_themes.map((theme, i) => (
                              <div
                                key={i}
                                style={{
                                  display: 'flex',
                                  gap: 8,
                                  alignItems: 'baseline',
                                  fontSize: 13,
                                  color: 'var(--t2)',
                                  lineHeight: 1.6,
                                  fontFamily: 'var(--font-body)',
                                }}
                              >
                                <span
                                  style={{
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: 10,
                                    color: 'var(--vl)',
                                    fontWeight: 600,
                                    flexShrink: 0,
                                    minWidth: 18,
                                  }}
                                >
                                  {String(i + 1).padStart(2, '0')}
                                </span>
                                {theme}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                    {dossier.interview_prep.talking_points &&
                      dossier.interview_prep.talking_points.length > 0 && (
                        <div>
                          <SubLabel>Talking Points</SubLabel>
                          {dossier.interview_prep.talking_points.map((point, i) => (
                            <Prose key={i}>
                              <p style={{ marginBottom: 6 }}>{point}</p>
                            </Prose>
                          ))}
                        </div>
                      )}

                    {dossier.interview_prep.technical_focus &&
                      dossier.interview_prep.technical_focus.length > 0 && (
                        <div>
                          <SubLabel>Technical Focus</SubLabel>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                            {dossier.interview_prep.technical_focus.map((t) => (
                              <TechPill key={t} name={t} />
                            ))}
                          </div>
                        </div>
                      )}

                    {dossier.interview_prep.likely_questions &&
                      dossier.interview_prep.likely_questions.length > 0 && (
                        <div>
                          <SubLabel>Likely Questions</SubLabel>
                          {dossier.interview_prep.likely_questions.map((q, i) => (
                            <QuoteBlock key={i}>{q}</QuoteBlock>
                          ))}
                        </div>
                      )}
                  </div>
                )}
              </>
            )}
          </IntelSection>
        </TabPanel>

        {/* ═══════════════════════════════════
            TAB: OUTREACH
            ═══════════════════════════════════ */}
        <TabPanel id="outreach" active={resolvedTab === 'outreach'}>
          {/* Team & Contacts */}
          <IntelSection
            label="Team & Contacts"
            index="1"
            isBuilding={isBuilding}
            hasContent={teamContacts.length > 0}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {teamContacts.map((contact, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    padding: '10px 0',
                    borderBottom:
                      i < teamContacts.length - 1 ? '1px solid var(--b)' : 'none',
                    flexWrap: 'wrap',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 500,
                        fontFamily: 'var(--font-body)',
                        color: 'var(--t)',
                      }}
                    >
                      {contact.name}
                    </div>
                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11,
                        color: 'var(--t3)',
                        marginTop: 1,
                        letterSpacing: '0.02em',
                      }}
                    >
                      {contact.title}
                      {contact.department && ` \u00B7 ${contact.department}`}
                    </div>
                  </div>
                  <a
                    href={
                      contact.linkedin_search_url ||
                      `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(contact.name)}`
                    }
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10,
                      letterSpacing: '0.04em',
                      textTransform: 'uppercase',
                      color: 'var(--vl)',
                      textDecoration: 'none',
                      padding: '4px 10px',
                      border: '1px solid var(--bv)',
                      borderRadius: 4,
                      whiteSpace: 'nowrap',
                      minHeight: 26,
                      display: 'inline-flex',
                      alignItems: 'center',
                      transition: 'all 0.2s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--vf)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent';
                    }}
                  >
                    LinkedIn <span aria-hidden="true" style={{ marginLeft: 4 }}>&rarr;</span>
                  </a>
                </div>
              ))}
            </div>
          </IntelSection>

          {/* Outreach Drafts */}
          <IntelSection
            label="Outreach Drafts"
            index="2"
            isBuilding={isBuilding}
            hasContent={hasData(dossier.outreach_draft)}
          >
            {dossier.outreach_draft && (
              <>
                {/* Check for raw text */}
                {typeof dossier.outreach_draft === 'string' ? (
                  <SmartProse data={dossier.outreach_draft} />
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                    {/* LinkedIn */}
                    {dossier.outreach_draft.linkedin_message && (
                      <div>
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginBottom: 8,
                            gap: 8,
                          }}
                        >
                          <SubLabel>LinkedIn Connection Request</SubLabel>
                          <CopyButton text={dossier.outreach_draft.linkedin_message} />
                        </div>
                        <div
                          style={{
                            background: 'var(--sf)',
                            border: '1px solid var(--b)',
                            borderRadius: 6,
                            padding: 14,
                            fontSize: 13,
                            fontFamily: 'var(--font-body)',
                            color: 'var(--t2)',
                            lineHeight: 1.65,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
                          {dossier.outreach_draft.linkedin_message}
                        </div>
                      </div>
                    )}

                    {/* Email */}
                    {dossier.outreach_draft.email_draft && (
                      <div>
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginBottom: 8,
                            gap: 8,
                          }}
                        >
                          <SubLabel>Email Draft</SubLabel>
                          <CopyButton text={dossier.outreach_draft.email_draft} />
                        </div>
                        <div
                          style={{
                            background: 'var(--sf)',
                            border: '1px solid var(--b)',
                            borderRadius: 6,
                            padding: 14,
                            fontSize: 13,
                            fontFamily: 'var(--font-body)',
                            color: 'var(--t2)',
                            lineHeight: 1.65,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
                          {dossier.outreach_draft.email_draft}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </IntelSection>
        </TabPanel>

        {/* ═══════════════════════════════════
            TAB: COMPENSATION
            ═══════════════════════════════════ */}
        <TabPanel id="compensation" active={resolvedTab === 'compensation'}>
          {/* Salary Estimate */}
          <IntelSection
            label="Salary Estimate"
            index="1"
            isBuilding={isBuilding}
            hasContent={hasData(salary)}
          >
            {salary && (
              <>
                {typeof salary === 'string' ? (
                  <SmartProse data={salary} />
                ) : (
                  <>
                    {/* Levels.fyi-style comp breakdown */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      {salary.total_comp && (
                        <div style={{
                          background: 'rgba(139, 92, 246, 0.06)',
                          border: '1px solid rgba(139, 92, 246, 0.15)',
                          borderRadius: 8,
                          padding: '14px 16px',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Total Compensation</span>
                          <span style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700, color: 'var(--vl)', letterSpacing: '-0.02em' }}>{salary.total_comp}</span>
                        </div>
                      )}

                      {salary.range && (
                        <div style={{
                          background: 'var(--sf)',
                          border: '1px solid var(--b)',
                          borderRadius: 8,
                          padding: '12px 16px',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Base Salary</span>
                          <span style={{ fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600, color: 'var(--t)' }}>{salary.range}</span>
                        </div>
                      )}

                      {salary.median && (
                        <div style={{
                          background: 'var(--sf)',
                          border: '1px solid var(--b)',
                          borderRadius: 8,
                          padding: '12px 16px',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Median</span>
                          <span style={{ fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600, color: 'var(--t)' }}>{salary.median}</span>
                        </div>
                      )}
                    </div>

                    {salary.source && (
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.04em', marginTop: 10 }}>
                        Source: {salary.source}
                      </div>
                    )}

                    {salary.by_level && salary.by_level.length > 0 && (
                      <div style={{ marginTop: 14 }}>
                        <SubLabel>By Level</SubLabel>
                        <div style={{
                          background: 'var(--sf)',
                          border: '1px solid var(--b)',
                          borderRadius: 8,
                          overflow: 'hidden',
                        }}>
                          {salary.by_level.map((row, i) => (
                            <div
                              key={i}
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                padding: '10px 16px',
                                borderBottom:
                                  i < (salary.by_level?.length ?? 0) - 1
                                    ? '1px solid var(--b)'
                                    : 'none',
                              }}
                            >
                              <span style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--t2)' }}>{row.level}</span>
                              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--vl)', fontWeight: 600 }}>{row.total_comp}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </IntelSection>

          {/* Recent News — hidden for now, TinyFish search returns irrelevant results */}
        </TabPanel>

        {/* ═══════════════════════════════════
            FOOTER
            ═══════════════════════════════════ */}
        <div style={{ marginTop: 32 }}>
          <Divider />
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              paddingTop: 14,
              flexWrap: 'wrap',
              gap: 8,
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--t3)',
                letterSpacing: '0.04em',
              }}
            >
              {completedSources}/{completedSources + failed.length} sources compiled
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                color: 'var(--t3)',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                opacity: 0.6,
              }}
            >
              Foxhound
            </span>
          </div>
        </div>

        {/* ═══════════════════════════════════
            Scoped styles
            ═══════════════════════════════════ */}
        <style>{`
          .dossier-skel {
            position: relative;
            overflow: hidden;
          }
          .dossier-skel::after {
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
            animation: dossier-shimmer 1.8s ease-in-out infinite;
          }
          @keyframes dossier-shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
          }
          @keyframes dossier-pulse-glow {
            0%, 100% { opacity: 1; box-shadow: 0 0 4px var(--v); }
            50% { opacity: 0.4; box-shadow: 0 0 8px var(--v); }
          }
          .dossier-pulse {
            animation: dossier-pulse-glow 1.2s ease-in-out infinite;
          }
          @keyframes dossier-fadein {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
          }

          /* Tab bar scrollbar hide */
          [role="tablist"]::-webkit-scrollbar {
            display: none;
          }

          @media (max-width: 480px) {
            .dossier-page {
              padding-left: 16px !important;
              padding-right: 16px !important;
            }
          }

          @media (max-width: 375px) {
            .dossier-page {
              padding-left: 12px !important;
              padding-right: 12px !important;
            }
          }

          @media (prefers-reduced-motion: reduce) {
            .dossier-skel::after {
              animation: none;
            }
            .dossier-pulse {
              animation: none;
            }
          }
        `}</style>
      </main>
    </AuthGuard>
  );
}
