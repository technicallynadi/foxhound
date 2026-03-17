"use client";

import { useState } from "react";
import {
  ChevronDown,
  Link as LinkIcon,
  MapPin,
  Cpu,
  ArrowRight,
  Clock,
  DollarSign,
  Layers,
  Sparkles,
} from "lucide-react";
import useSWR from "swr";
import TopBar from "@/components/top-bar";
import GlassButton from "@/components/ui/glass-button";
import {
  fetchOpportunities,
  fetchOpportunity,
  type Opportunity,
} from "@/lib/api";
import { useRouter } from "next/navigation";
import {
  getTierConfig,
  getStateBadge,
  DIMENSION_LABELS,
  scoreColor,
} from "@/lib/shared";

const STATE_OPTIONS = [
  { label: "All States", value: "" },
  { label: "Approved", value: "approved" },
  { label: "Executing", value: "executing" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
];

export default function WorkItemsPage() {
  const router = useRouter();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState("approved");
  const [showStateDropdown, setShowStateDropdown] = useState(false);

  const { data } = useSWR(
    ["work-items", stateFilter],
    () =>
      fetchOpportunities({
        state: stateFilter || undefined,
        sort_by: "date",
        limit: 50,
      }),
    { fallbackData: { items: [], total: 0 }, revalidateOnFocus: false }
  );

  const items = data?.items ?? [];

  const { data: detail } = useSWR(
    selectedId ? ["work-item", selectedId] : null,
    () => fetchOpportunity(selectedId!),
    { revalidateOnFocus: false }
  );

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar activeTab="work-items" />

      <div className="flex flex-1 overflow-hidden">
        {/* Left List Pane */}
        <div className="w-[440px] shrink-0 bg-glass-fill backdrop-blur-xl border-r border-glass-border flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-glass-border">
            <span className="text-sm font-semibold text-text-primary">
              {items.length} work item{items.length !== 1 ? "s" : ""}
            </span>
            <div className="relative">
              <button
                onClick={() => setShowStateDropdown(!showStateDropdown)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text-secondary border border-glass-border rounded-lg hover:border-glass-border-strong transition-colors"
              >
                {STATE_OPTIONS.find((s) => s.value === stateFilter)?.label ??
                  "All States"}
                <ChevronDown className="w-3 h-3" />
              </button>
              {showStateDropdown && (
                <div className="absolute top-full mt-1 right-0 w-32 bg-bg-card border border-glass-border rounded-lg shadow-xl z-20 py-1">
                  {STATE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => {
                        setStateFilter(opt.value);
                        setShowStateDropdown(false);
                      }}
                      className={`w-full text-left px-3 py-2 text-xs hover:bg-bg-input transition-colors ${
                        stateFilter === opt.value
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

          <div className="flex-1 overflow-y-auto">
            {items.map((item) => {
              const isSelected = selectedId === item.opportunity_id;
              return (
                <button
                  key={item.opportunity_id}
                  onClick={() => setSelectedId(item.opportunity_id)}
                  className={`w-full text-left px-5 py-4 border-b border-glass-border transition-colors ${
                    isSelected
                      ? "bg-accent-purple/[0.12]"
                      : "hover:bg-[rgba(255,255,255,0.02)]"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${getStateBadge(item.state)}`}
                    >
                      {item.state}
                    </span>
                    <span className="text-sm font-bold font-mono text-accent-purple">
                      {Math.round(item.opportunity_score)}/35
                    </span>
                  </div>
                  <p className="text-sm font-medium text-text-primary line-clamp-2 mb-1">
                    {item.title}
                  </p>
                  <p className="text-xs text-text-muted">
                    {item.matched_topic || "No topic"}
                  </p>
                </button>
              );
            })}

            {items.length === 0 && (
              <div className="flex flex-col items-center justify-center py-20 text-text-muted px-5">
                <p className="text-sm mb-1">No work items found</p>
                <p className="text-xs">
                  Approve opportunities to create work items
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right Detail Pane */}
        <div className="flex-1 overflow-y-auto p-7">
          {!selectedId || !detail ? (
            <div className="flex items-center justify-center h-full text-text-muted text-sm">
              Select a work item to view details
            </div>
          ) : (
            <div className="max-w-2xl">
              <div className="flex items-center gap-3 mb-4">
                <span
                  className={`px-2.5 py-0.5 rounded text-xs font-semibold uppercase ${getStateBadge(detail.state)}`}
                >
                  {detail.state}
                </span>
                {(() => {
                  const tier = getTierConfig(detail.signal_tier);
                  return (
                    <span
                      className={`px-2.5 py-0.5 rounded text-xs font-medium ${tier.color} ${tier.bg}`}
                    >
                      {tier.label}
                    </span>
                  );
                })()}
                <span className="text-sm font-mono font-bold text-accent-purple">
                  {Math.round(detail.opportunity_score)}/35
                </span>
              </div>

              <h1 className="text-[22px] font-bold text-text-primary mb-3">
                {detail.title}
              </h1>

              <div className="border-t border-glass-border my-5" />

              <div className="mb-5">
                <span className="text-xs text-text-muted uppercase tracking-wider font-medium block mb-2">
                  Summary
                </span>
                <p className="text-sm text-text-secondary leading-relaxed">
                  {detail.enrichment_summary || detail.description}
                </p>
              </div>

              <div className="border-t border-glass-border my-5" />

              <div className="mb-5">
                <span className="text-xs text-text-muted uppercase tracking-wider font-medium block mb-3">
                  Scoring Dimensions
                </span>
                <div className="grid grid-cols-2 gap-x-8 gap-y-3">
                  {DIMENSION_LABELS.map((dim) => {
                    const value = detail[dim.key] as number;
                    return (
                      <div
                        key={dim.key}
                        className="flex items-center justify-between"
                      >
                        <span className="text-sm text-text-secondary">
                          {dim.label}
                        </span>
                        <span
                          className={`text-sm font-mono font-bold ${scoreColor(value)}`}
                        >
                          {value}/{dim.max}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="border-t border-glass-border my-5" />

              {/* Build Preview */}
              <div className="mb-5">
                <span className="text-xs text-text-muted uppercase tracking-wider font-medium block mb-3">
                  Build Preview
                </span>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  {detail.suggested_stack && (
                    <div className="flex items-start gap-2">
                      <Layers className="w-4 h-4 text-text-muted mt-0.5 shrink-0" />
                      <div>
                        <p className="text-xs text-text-muted">Stack</p>
                        <p className="text-sm text-text-primary">
                          {detail.suggested_stack}
                        </p>
                      </div>
                    </div>
                  )}
                  {detail.estimated_build_time && (
                    <div className="flex items-start gap-2">
                      <Clock className="w-4 h-4 text-text-muted mt-0.5 shrink-0" />
                      <div>
                        <p className="text-xs text-text-muted">Build Time</p>
                        <p className="text-sm text-text-primary">
                          {detail.estimated_build_time}
                        </p>
                      </div>
                    </div>
                  )}
                  {detail.estimated_build_cost && (
                    <div className="flex items-start gap-2">
                      <DollarSign className="w-4 h-4 text-text-muted mt-0.5 shrink-0" />
                      <div>
                        <p className="text-xs text-text-muted">Cost</p>
                        <p className="text-sm text-text-primary">
                          {detail.estimated_build_cost}
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                {detail.mvp_features.length > 0 && (
                  <div className="mb-4">
                    <p className="text-xs text-text-muted mb-2">MVP Features</p>
                    <ul className="space-y-1.5">
                      {detail.mvp_features.map((f, i) => (
                        <li
                          key={i}
                          className="flex items-start gap-2 text-sm text-text-secondary"
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-accent-purple mt-1.5 shrink-0" />
                          {f}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              <div className="border-t border-glass-border my-5" />

              {/* Meta */}
              <div className="flex flex-wrap items-center gap-4 text-xs text-text-muted mb-6">
                {detail.source_url && (
                  <a
                    href={detail.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-accent-purple hover:underline"
                  >
                    <LinkIcon className="w-3 h-3" />
                    {detail.source_type}
                  </a>
                )}
                <span className="flex items-center gap-1">
                  <MapPin className="w-3 h-3" />
                  {detail.matched_topic}
                </span>
                {detail.ai_exposure_score > 0 && (
                  <span className="flex items-center gap-1">
                    <Cpu className="w-3 h-3" />
                    AI: {Math.round(detail.ai_exposure_score)}/10
                  </span>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-3">
                {detail.state === "approved" && (
                  <GlassButton
                    variant="primary"
                    onClick={() =>
                      router.push(`/builds/${detail.opportunity_id}`)
                    }
                  >
                    <Sparkles className="w-4 h-4" />
                    Start Build
                  </GlassButton>
                )}
                {detail.state === "executing" && (
                  <GlassButton
                    variant="ghost"
                    className="text-accent-purple border-accent-purple/20"
                    onClick={() =>
                      router.push(`/builds/${detail.opportunity_id}`)
                    }
                  >
                    Watch Execution
                  </GlassButton>
                )}
                <button
                  onClick={() => router.push(`/work-items/${detail.opportunity_id}`)}
                  className="flex items-center gap-1.5 text-xs text-accent-purple hover:underline"
                >
                  View full details
                  <ArrowRight className="w-3 h-3" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {showStateDropdown && (
        <div
          className="fixed inset-0 z-10"
          onClick={() => setShowStateDropdown(false)}
        />
      )}
    </div>
  );
}
