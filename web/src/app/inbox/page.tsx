"use client";

import { useState, useCallback } from "react";
import {
  ChevronDown,
  Link as LinkIcon,
  Tag,
  Cpu,
  ArrowRight,
} from "lucide-react";
import useSWR from "swr";
import TopBar from "@/components/top-bar";
import {
  fetchOpportunities,
  fetchOpportunity,
  approveOpportunity,
  dismissOpportunity,
  type Opportunity,
} from "@/lib/api";
import { useRouter } from "next/navigation";
import {
  getTierConfig,
  DIMENSION_LABELS,
  scoreColor,
  confidenceBadge,
} from "@/lib/shared";

const SORT_OPTIONS = [
  { label: "Score", value: "score" },
  { label: "Date", value: "date" },
];

export default function OpportunitiesPage() {
  const router = useRouter();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState("score");
  const [showSortDropdown, setShowSortDropdown] = useState(false);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());

  const { data, mutate } = useSWR(
    ["opportunities", sortBy],
    () => fetchOpportunities({ sort_by: sortBy, limit: 50 }),
    { fallbackData: { items: [], total: 0 }, revalidateOnFocus: false }
  );

  const opportunities =
    data?.items.filter((o) => !dismissedIds.has(o.opportunity_id)) ?? [];

  const { data: detail } = useSWR(
    selectedId ? ["opportunity", selectedId] : null,
    () => fetchOpportunity(selectedId!),
    { revalidateOnFocus: false }
  );

  const handleApprove = useCallback(
    async (id: string) => {
      try {
        await approveOpportunity(id);
        mutate();
      } catch {
        // continue regardless
      }
      router.push("/dashboard");
    },
    [mutate, router]
  );

  const handleDismiss = useCallback(
    async (id: string) => {
      setDismissedIds((prev) => new Set(prev).add(id));
      if (selectedId === id) setSelectedId(null);
      try {
        await dismissOpportunity(id);
        mutate();
      } catch {
        // keep dismissed in UI
      }
    },
    [mutate, selectedId]
  );

  const col1 = DIMENSION_LABELS.slice(0, 3);
  const col2 = DIMENSION_LABELS.slice(3);

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar activeTab="scout-inbox" />

      <div className="flex flex-1 overflow-hidden">
        {/* Left List Pane */}
        <div className="w-[440px] shrink-0 bg-glass-fill backdrop-blur-xl border-r border-glass-border flex flex-col overflow-hidden">
          {/* List header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-glass-border">
            <span className="text-sm text-text-secondary">
              {opportunities.length} opportunit
              {opportunities.length !== 1 ? "ies" : "y"}
            </span>
            <div className="relative">
              <button
                onClick={() => setShowSortDropdown(!showSortDropdown)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text-secondary border border-glass-border rounded-lg hover:border-glass-border-strong transition-colors"
              >
                Sort: {SORT_OPTIONS.find((s) => s.value === sortBy)?.label}
                <ChevronDown className="w-3 h-3" />
              </button>
              {showSortDropdown && (
                <div className="absolute top-full mt-1 right-0 w-28 bg-bg-card border border-glass-border rounded-lg shadow-xl z-20 py-1">
                  {SORT_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => {
                        setSortBy(opt.value);
                        setShowSortDropdown(false);
                      }}
                      className={`w-full text-left px-3 py-2 text-xs hover:bg-bg-input transition-colors ${
                        sortBy === opt.value
                          ? "text-accent-purple"
                          : "text-text-secondary"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* List items */}
          <div className="flex-1 overflow-y-auto">
            {opportunities.map((opp) => {
              const tier = getTierConfig(opp.signal_tier);
              const isSelected = selectedId === opp.opportunity_id;

              return (
                <button
                  key={opp.opportunity_id}
                  onClick={() => setSelectedId(opp.opportunity_id)}
                  className={`w-full text-left px-5 py-4 border-b border-glass-border space-y-2 transition-colors ${
                    isSelected
                      ? "bg-accent-purple/[0.12]"
                      : "hover:bg-[rgba(255,255,255,0.02)]"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold ${tier.color} ${tier.bg}`}
                    >
                      {tier.label}
                    </span>
                    <span className="text-xs font-bold font-mono text-accent-purple">
                      {Math.round(opp.opportunity_score)}/35
                    </span>
                  </div>
                  <p className="text-sm font-semibold text-text-primary line-clamp-2">
                    {opp.title}
                  </p>
                  <p className="text-xs text-text-muted">
                    {opp.tags?.length ?? 0} signal
                    {(opp.tags?.length ?? 0) !== 1 ? "s" : ""} —{" "}
                    {opp.source_type ?? "unknown"}
                  </p>
                </button>
              );
            })}

            {opportunities.length === 0 && (
              <div className="flex flex-col items-center justify-center py-20 text-text-muted px-5">
                <p className="text-sm mb-1">No opportunities found</p>
                <p className="text-xs">
                  Run a scout scan to discover new opportunities
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right Detail Pane */}
        <div className="flex-1 overflow-y-auto">
          {!selectedId || !detail ? (
            <div className="flex items-center justify-center h-full text-text-muted text-sm">
              Select an opportunity to view details
            </div>
          ) : (
            <div className="p-7 space-y-5">
              {/* Top row: tier badge left, confidence right */}
              <div className="flex items-center justify-between">
                {(() => {
                  const tier = getTierConfig(detail.signal_tier);
                  return (
                    <span
                      className={`px-3 py-1 rounded-md text-xs font-semibold ${tier.color} ${tier.bg}`}
                    >
                      {tier.label}
                    </span>
                  );
                })()}
                <div className="flex items-center gap-1.5">
                  <span className="text-sm text-text-muted">Confidence:</span>
                  <span className="text-lg font-bold font-mono text-accent-purple">
                    {Math.round(detail.opportunity_score)}/35
                  </span>
                  {(() => {
                    const badge = confidenceBadge(detail.confidence_level);
                    return (
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${badge.cls}`}
                      >
                        {badge.label}
                      </span>
                    );
                  })()}
                </div>
              </div>

              {/* Title */}
              <h1 className="text-[22px] font-bold text-text-primary leading-snug">
                {detail.title}
              </h1>

              {/* State */}
              <div className="flex items-center gap-2">
                <span className="text-[13px] text-text-muted">State:</span>
                <span
                  className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${
                    detail.state === "suggested"
                      ? "text-tier-workaround bg-tier-workaround/15"
                      : detail.state === "approved"
                      ? "text-accent-green bg-accent-green/15"
                      : detail.state === "rejected" ||
                        detail.state === "dismissed"
                      ? "text-accent-red bg-accent-red/15"
                      : "text-text-muted bg-bg-input"
                  }`}
                >
                  {detail.state?.toUpperCase()}
                </span>
              </div>

              {/* Divider */}
              <div className="h-px bg-glass-border" />

              {/* Enrichment Summary */}
              <div>
                <h2 className="text-sm font-semibold text-text-primary mb-2">
                  Enrichment Summary
                </h2>
                <p className="text-sm text-text-secondary leading-relaxed">
                  {detail.enrichment_summary || detail.description}
                </p>
              </div>

              {/* Divider */}
              <div className="h-px bg-glass-border" />

              {/* Scoring Dimensions */}
              <div>
                <h2 className="text-sm font-semibold text-text-primary mb-3">
                  Scoring Dimensions
                </h2>
                <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
                  {[...col1, ...col2].map((dim, i) => {
                    const value = detail[dim.key] as number;
                    const col = i < 3 ? "col1" : "col2";
                    return (
                      <div
                        key={dim.key}
                        className="flex items-center justify-between"
                        style={{
                          gridColumn: col === "col1" ? 1 : 2,
                          gridRow: (i % 3) + 1,
                        }}
                      >
                        <span className="text-xs text-text-secondary">
                          {dim.label}
                        </span>
                        <span
                          className={`text-xs font-mono font-semibold ${scoreColor(value)}`}
                        >
                          {value}/{dim.max}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Divider */}
              <div className="h-px bg-glass-border" />

              {/* Meta - vertical stack with icons */}
              <div className="space-y-2">
                {detail.source_url && (
                  <a
                    href={detail.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-[13px] text-accent-purple hover:underline"
                  >
                    <LinkIcon className="w-3.5 h-3.5 text-text-muted" />
                    {detail.source_url
                      .replace(/^https?:\/\//, "")
                      .slice(0, 40)}
                  </a>
                )}
                {detail.matched_topic && (
                  <div className="flex items-center gap-2 text-[13px] text-text-secondary">
                    <Tag className="w-3.5 h-3.5 text-text-muted" />
                    {detail.matched_topic}
                  </div>
                )}
                {detail.ai_exposure_score > 0 && (
                  <div className="flex items-center gap-2 text-[13px] text-text-secondary">
                    <Cpu className="w-3.5 h-3.5 text-text-muted" />
                    {detail.ai_exposure_angle ||
                      `Greenfield (AI exposure: ${Math.round(detail.ai_exposure_score)}/10)`}
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={() => handleDismiss(detail.opportunity_id)}
                  className="px-6 py-3 rounded-lg border border-glass-border text-sm font-medium text-text-muted hover:bg-glass-fill transition-colors"
                >
                  Reject
                </button>
                <button
                  onClick={() => handleApprove(detail.opportunity_id)}
                  className="flex items-center gap-2 px-6 py-3 rounded-lg bg-gradient-to-b from-accent-purple to-accent-purple-dim text-white text-sm font-semibold hover:opacity-90 transition-opacity"
                >
                  Approve
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>

              {/* View full detail page */}
              <button
                onClick={() => router.push(`/inbox/${detail.opportunity_id}`)}
                className="flex items-center gap-1.5 text-xs text-accent-purple hover:underline pt-3"
              >
                View full details
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Close dropdown overlay */}
      {showSortDropdown && (
        <div
          className="fixed inset-0 z-10"
          onClick={() => setShowSortDropdown(false)}
        />
      )}
    </div>
  );
}
