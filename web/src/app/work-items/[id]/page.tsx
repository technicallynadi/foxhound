"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import {
  ArrowLeft,
  ArrowRight,
  Link as LinkIcon,
  Tag,
  Cpu,
  Calendar,
  Activity,
  Clock,
  DollarSign,
  Layers,
  Sparkles,
} from "lucide-react";
import TopBar from "@/components/top-bar";
import { fetchOpportunity } from "@/lib/api";
import {
  getTierConfig,
  getStateBadge,
  DIMENSION_LABELS,
  scoreColor,
} from "@/lib/shared";

export default function WorkItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { data: item } = useSWR(
    id ? `work-item-${id}` : null,
    () => fetchOpportunity(id),
    { revalidateOnFocus: false }
  );

  if (!item) {
    return (
      <div className="min-h-screen">
        <TopBar activeTab="work-items" />
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="w-6 h-6 border-2 border-accent-purple border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  const tier = getTierConfig(item.signal_tier);
  const col1 = DIMENSION_LABELS.slice(0, 3);
  const col2 = DIMENSION_LABELS.slice(3);

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar activeTab="work-items" />

      <div className="flex flex-1 overflow-hidden">
        {/* Left Column */}
        <div className="animate-fade-in-up flex-1 overflow-y-auto p-8 space-y-6">
          {/* Back nav */}
          <button
            onClick={() => router.push("/work-items")}
            className="flex items-center gap-2 text-sm text-accent-purple hover:opacity-80 transition-opacity"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Work Items
          </button>

          {/* Hero Card */}
          <div className="bg-glass-fill backdrop-blur-xl border border-glass-border-strong rounded-2xl p-6 bg-gradient-to-b from-accent-purple/[0.04] to-transparent">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <span className={`px-3 py-1 rounded-md text-xs font-semibold ${tier.color} ${tier.bg}`}>
                  {tier.label}
                </span>
                <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase ${getStateBadge(item.state)}`}>
                  {item.state}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-sm text-text-muted">Score:</span>
                <span className="text-[22px] font-bold font-mono text-accent-purple">
                  {Math.round(item.opportunity_score)}
                </span>
                <span className="text-sm text-text-muted">/35</span>
              </div>
            </div>

            <h1 className="text-2xl font-bold text-text-primary leading-snug mb-4">
              {item.title}
            </h1>

            <p className="text-sm text-text-secondary leading-relaxed">
              {item.enrichment_summary || item.description}
            </p>
          </div>

          {/* Scoring Dimensions Card */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-6">
            <h2 className="text-base font-semibold text-text-primary mb-4">Scoring Dimensions</h2>
            <div className="grid grid-cols-2 gap-x-4">
              <div className="space-y-3">
                {col1.map((dim) => {
                  const value = item[dim.key] as number;
                  return (
                    <div key={dim.key} className="flex items-center justify-between">
                      <span className="text-[13px] text-text-secondary">{dim.label}</span>
                      <span className={`text-[13px] font-mono font-semibold ${scoreColor(value)}`}>
                        {value}/{dim.max}
                      </span>
                    </div>
                  );
                })}
              </div>
              <div className="space-y-3">
                {col2.map((dim) => {
                  const value = item[dim.key] as number;
                  return (
                    <div key={dim.key} className="flex items-center justify-between">
                      <span className="text-[13px] text-text-secondary">{dim.label}</span>
                      <span className={`text-[13px] font-mono font-semibold ${scoreColor(value)}`}>
                        {value}/{dim.max}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Build Preview Card */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-6">
            <h2 className="text-base font-semibold text-text-primary mb-4 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-accent-purple" />
              Build Preview
            </h2>
            <div className="grid grid-cols-2 gap-4 mb-4">
              {item.suggested_stack && (
                <div className="flex items-start gap-2">
                  <Layers className="w-4 h-4 text-text-muted mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-text-muted">Suggested Stack</p>
                    <p className="text-sm text-text-primary">{item.suggested_stack}</p>
                  </div>
                </div>
              )}
              {item.estimated_build_time && (
                <div className="flex items-start gap-2">
                  <Clock className="w-4 h-4 text-text-muted mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-text-muted">Build Time</p>
                    <p className="text-sm text-text-primary">{item.estimated_build_time}</p>
                  </div>
                </div>
              )}
              {item.estimated_build_cost && (
                <div className="flex items-start gap-2">
                  <DollarSign className="w-4 h-4 text-text-muted mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-text-muted">Estimated Cost</p>
                    <p className="text-sm text-text-primary">{item.estimated_build_cost}</p>
                  </div>
                </div>
              )}
            </div>
            {item.mvp_features.length > 0 && (
              <div className="mb-4">
                <p className="text-xs text-text-muted mb-2">MVP Features</p>
                <ul className="space-y-1.5">
                  {item.mvp_features.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                      <span className="w-1.5 h-1.5 rounded-full bg-accent-purple mt-1.5 shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {item.distribution_channels.length > 0 && (
              <div>
                <p className="text-xs text-text-muted mb-2">Distribution Channels</p>
                <div className="flex flex-wrap gap-2">
                  {item.distribution_channels.map((ch) => (
                    <span
                      key={ch}
                      className="px-2.5 py-1 text-xs bg-[rgba(255,255,255,0.02)] border border-glass-border rounded-full text-text-secondary"
                    >
                      {ch}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column */}
        <div className="animate-fade-in-right animation-delay-100 w-[380px] shrink-0 border-l border-glass-border overflow-y-auto p-6 space-y-5">
          {/* Metadata */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-5">
            <h3 className="text-[15px] font-semibold text-text-primary mb-3.5">Metadata</h3>
            <div className="space-y-3">
              {item.source_url && (
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-[13px] text-accent-purple hover:underline"
                >
                  <LinkIcon className="w-3.5 h-3.5 text-text-muted" />
                  {item.source_url.replace(/^https?:\/\//, "").slice(0, 35)}...
                </a>
              )}
              {item.matched_topic && (
                <div className="flex items-center gap-2">
                  <Tag className="w-3.5 h-3.5 text-text-muted" />
                  <span className="text-[13px] text-text-secondary">{item.matched_topic}</span>
                </div>
              )}
              {item.ai_exposure_score > 0 && (
                <div className="flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5 text-text-muted" />
                  <span className="text-[13px] text-text-secondary">
                    {item.ai_exposure_angle || `AI exposure: ${Math.round(item.ai_exposure_score)}/10`}
                  </span>
                </div>
              )}
              <div className="flex items-center gap-2">
                <Calendar className="w-3.5 h-3.5 text-text-muted" />
                <span className="text-[13px] text-text-secondary">
                  Created: {new Date(item.created_at).toLocaleDateString()}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Activity className="w-3.5 h-3.5 text-text-muted" />
                <span className="text-[13px] text-text-secondary">
                  {item.tags?.length ?? 0} signals analyzed
                </span>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-5 bg-gradient-to-b from-accent-purple/[0.03] to-transparent">
            <h3 className="text-[15px] font-semibold text-text-primary mb-3.5">Actions</h3>
            <div className="space-y-3">
              {item.state === "approved" && (
                <button
                  onClick={() => router.push(`/builds/${item.opportunity_id}`)}
                  className="w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-gradient-to-b from-accent-purple to-accent-purple-dim text-white text-sm font-semibold transition-opacity hover:opacity-90"
                >
                  <Sparkles className="w-4 h-4" />
                  Start Build
                </button>
              )}
              {item.state === "executing" && (
                <button
                  onClick={() => router.push(`/builds/${item.opportunity_id}`)}
                  className="w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg border border-accent-purple/30 text-sm font-medium text-accent-purple transition-colors hover:bg-accent-purple/[0.08]"
                >
                  Watch Execution
                  <ArrowRight className="w-4 h-4" />
                </button>
              )}
              {item.state === "completed" && (
                <button
                  onClick={() => router.push(`/builds/${item.opportunity_id}`)}
                  className="w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-gradient-to-b from-accent-purple to-accent-purple-dim text-white text-sm font-semibold transition-opacity hover:opacity-90"
                >
                  View Build
                  <ArrowRight className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
