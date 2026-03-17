"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { ExternalLink, Loader, RefreshCw } from "lucide-react";
import TopBar from "@/components/top-bar";
import GlassCard from "@/components/ui/glass-card";
import GlassButton from "@/components/ui/glass-button";
import { fetchOpportunities } from "@/lib/api";

export default function BuildsPage() {
  const router = useRouter();

  const { data: approved } = useSWR(
    "builds-approved",
    () => fetchOpportunities({ state: "approved", limit: 10 }),
    { fallbackData: { items: [], total: 0 }, revalidateOnFocus: false }
  );
  const { data: completed } = useSWR(
    "builds-completed",
    () => fetchOpportunities({ state: "completed" as string, limit: 10 }),
    { fallbackData: { items: [], total: 0 }, revalidateOnFocus: false }
  );

  const builds = [...(approved?.items ?? []), ...(completed?.items ?? [])];
  const totalRuns = builds.length;

  return (
    <div className="min-h-screen">
      <TopBar activeTab="builds" />

      <div className="max-w-5xl mx-auto px-10 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-text-primary">Your Builds</h1>
          <span className="text-sm text-text-muted">
            {totalRuns} completed run{totalRuns !== 1 ? "s" : ""}
          </span>
        </div>

        <div className="space-y-5">
          {builds.length > 0 ? (
            builds.map((opp) => {
              const isExecuting = opp.state === "approved";
              return (
                <GlassCard
                  key={opp.opportunity_id}
                  padding="p-6"
                  className={
                    isExecuting ? "border-accent-purple/20" : ""
                  }
                >
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-lg font-semibold text-text-primary">
                      {opp.title}
                    </h3>
                    {isExecuting ? (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-accent-purple/[0.12] text-accent-purple">
                        <Loader className="w-2.5 h-2.5 animate-spin" />
                        EXECUTING
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-accent-green/[0.12] text-accent-green">
                        <span className="w-1.5 h-1.5 rounded-full bg-accent-green" />
                        COMPLETED
                      </span>
                    )}
                  </div>

                  <p className="text-[13px] text-text-secondary leading-relaxed mb-2">
                    {opp.enrichment_summary || opp.description}
                  </p>

                  {opp.suggested_stack && (
                    <p className="font-mono text-xs text-accent-purple mb-3">
                      {opp.suggested_stack}
                    </p>
                  )}

                  <div className="h-px bg-glass-border my-4" />

                  {isExecuting ? (
                    <>
                      <p className="text-xs text-text-secondary mb-2">
                        Harness: execute (step 3/6)
                      </p>
                      <div className="w-full h-1.5 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden mb-4">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-accent-purple to-accent-blue"
                          style={{ width: "50%" }}
                        />
                      </div>
                      <div className="flex items-center gap-3">
                        <GlassButton
                          variant="ghost"
                          className="text-accent-purple border-accent-purple/20"
                          onClick={() =>
                            router.push(`/builds/${opp.opportunity_id}`)
                          }
                        >
                          Watch Execution
                        </GlassButton>
                        <GlassButton variant="ghost">Cancel</GlassButton>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-6 mb-4">
                        {opp.estimated_build_cost && (
                          <div>
                            <p className="font-mono text-base font-semibold text-text-primary">
                              {opp.estimated_build_cost}
                            </p>
                            <p className="text-[11px] text-text-muted">
                              Build cost
                            </p>
                          </div>
                        )}
                        {opp.estimated_build_time && (
                          <div>
                            <p className="font-mono text-base font-semibold text-text-primary">
                              {opp.estimated_build_time}
                            </p>
                            <p className="text-[11px] text-text-muted">
                              Build time
                            </p>
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <GlassButton
                          onClick={() =>
                            router.push(`/builds/${opp.opportunity_id}`)
                          }
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                          View Site
                        </GlassButton>
                        <GlassButton variant="ghost">
                          <RefreshCw className="w-3.5 h-3.5" />
                          Run Maintenance
                        </GlassButton>
                      </div>
                    </>
                  )}
                </GlassCard>
              );
            })
          ) : (
            <GlassCard padding="p-12" className="text-center">
              <p className="text-text-muted">
                No builds yet. Approve an opportunity to start building.
              </p>
            </GlassCard>
          )}
        </div>
      </div>
    </div>
  );
}
