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
} from "lucide-react";
import TopBar from "@/components/top-bar";
import { fetchOpportunity, approveOpportunity, dismissOpportunity } from "@/lib/api";
import {
  getTierConfig,
  DIMENSION_LABELS,
  scoreColor,
  confidenceBadge,
} from "@/lib/shared";

export default function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { data: opp } = useSWR(
    id ? `opportunity-${id}` : null,
    () => fetchOpportunity(id),
    { revalidateOnFocus: false }
  );

  async function handleApprove() {
    if (!opp) return;
    try {
      await approveOpportunity(opp.opportunity_id);
    } catch {
      // Continue regardless
    }
    router.push("/dashboard");
  }

  async function handleReject() {
    if (!opp) return;
    try {
      await dismissOpportunity(opp.opportunity_id);
    } catch {
      // Continue regardless
    }
    router.push("/inbox");
  }

  if (!opp) {
    return (
      <div className="min-h-screen">
        <TopBar />
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="w-6 h-6 border-2 border-accent-purple border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  const tier = getTierConfig(opp.signal_tier);
  const conf = confidenceBadge(opp.confidence_level);
  const col1 = DIMENSION_LABELS.slice(0, 3);
  const col2 = DIMENSION_LABELS.slice(3);

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* Left Column */}
        <div className="animate-fade-in-up flex-1 overflow-y-auto p-8 space-y-6">
          {/* Back nav */}
          <button
            onClick={() => router.push("/inbox")}
            className="flex items-center gap-2 text-sm text-accent-purple hover:opacity-80 transition-opacity"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Inbox
          </button>

          {/* Hero Card */}
          <div className="bg-glass-fill backdrop-blur-xl border border-glass-border-strong rounded-2xl p-6 bg-gradient-to-b from-accent-purple/[0.04] to-transparent">
            <div className="flex items-center justify-between mb-5">
              <span className={`px-3 py-1 rounded-md text-xs font-semibold ${tier.color} ${tier.bg}`}>
                {tier.label}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-sm text-text-muted">Confidence:</span>
                <span className="text-[22px] font-bold font-mono text-accent-purple">
                  {Math.round(opp.opportunity_score)}
                </span>
                <span className="text-sm text-text-muted">/35</span>
                <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${conf.cls}`}>
                  {conf.label}
                </span>
              </div>
            </div>

            <h1 className="text-2xl font-bold text-text-primary leading-snug mb-4">
              {opp.title}
            </h1>

            <div className="flex items-center gap-2">
              <span className="text-[13px] text-text-muted">State:</span>
              <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${
                opp.state === "suggested"
                  ? "text-tier-workaround bg-tier-workaround/15"
                  : opp.state === "approved"
                  ? "text-accent-green bg-accent-green/15"
                  : "text-text-muted bg-bg-input"
              }`}>
                {opp.state?.toUpperCase()}
              </span>
            </div>
          </div>

          {/* Enrichment Summary Card */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-6">
            <h2 className="text-base font-semibold text-text-primary mb-4">Enrichment Summary</h2>
            <p className="text-sm text-text-secondary leading-relaxed">
              {opp.enrichment_summary || opp.description}
            </p>
          </div>

          {/* Scoring Dimensions Card */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-6">
            <h2 className="text-base font-semibold text-text-primary mb-4">Scoring Dimensions</h2>
            <div className="grid grid-cols-2 gap-x-4">
              <div className="space-y-3">
                {col1.map((dim) => {
                  const value = opp[dim.key] as number;
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
                  const value = opp[dim.key] as number;
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
        </div>

        {/* Right Column */}
        <div className="animate-fade-in-right animation-delay-100 w-[380px] shrink-0 border-l border-glass-border overflow-y-auto p-6 space-y-5">
          {/* Signal Sources */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-5">
            <h3 className="text-[15px] font-semibold text-text-primary mb-3.5">Signal Sources</h3>
            <div className="space-y-3">
              {opp.source_url && (
                <a
                  href={opp.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-[13px] text-accent-purple hover:underline"
                >
                  <LinkIcon className="w-3.5 h-3.5 text-text-muted" />
                  {opp.source_url.replace(/^https?:\/\//, "").slice(0, 35)}...
                </a>
              )}
              {(opp.tags ?? []).length > 0 && (
                <p className="text-xs text-text-muted">+ {opp.tags!.length} signals analyzed</p>
              )}
            </div>
          </div>

          {/* Metadata */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-5">
            <h3 className="text-[15px] font-semibold text-text-primary mb-3.5">Metadata</h3>
            <div className="space-y-3">
              {opp.matched_topic && (
                <div className="flex items-center gap-2">
                  <Tag className="w-3.5 h-3.5 text-text-muted" />
                  <span className="text-[13px] text-text-secondary">{opp.matched_topic}</span>
                </div>
              )}
              {opp.ai_exposure_score > 0 && (
                <div className="flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5 text-text-muted" />
                  <span className="text-[13px] text-text-secondary">
                    {opp.ai_exposure_angle || `AI exposure: ${Math.round(opp.ai_exposure_score)}/10`}
                  </span>
                </div>
              )}
              <div className="flex items-center gap-2">
                <Calendar className="w-3.5 h-3.5 text-text-muted" />
                <span className="text-[13px] text-text-secondary">
                  Discovered: {new Date(opp.created_at).toLocaleDateString()}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Activity className="w-3.5 h-3.5 text-text-muted" />
                <span className="text-[13px] text-text-secondary">
                  {opp.tags?.length ?? 0} total signals analyzed
                </span>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="bg-glass-fill backdrop-blur-lg border border-glass-border rounded-xl p-5 bg-gradient-to-b from-accent-purple/[0.03] to-transparent">
            <h3 className="text-[15px] font-semibold text-text-primary mb-3.5">Actions</h3>
            <div className="space-y-3">
              <button
                onClick={handleApprove}
                className="w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-gradient-to-b from-accent-purple to-accent-purple-dim text-white text-sm font-semibold transition-opacity hover:opacity-90"
              >
                Approve &amp; Build
                <ArrowRight className="w-4 h-4" />
              </button>
              <button
                onClick={() => router.push(`/inbox/${id}/edit`)}
                className="w-full px-6 py-3 rounded-lg border border-glass-border-strong text-sm font-medium text-text-primary transition-colors hover:bg-glass-fill"
              >
                Edit Before Approving
              </button>
              <button
                onClick={handleReject}
                className="w-full px-6 py-3 rounded-lg border border-glass-border text-sm font-medium text-text-muted transition-colors hover:bg-glass-fill"
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
