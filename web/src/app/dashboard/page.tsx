"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import {
  ArrowRight,
  Radar,
  Zap,
  Send,
  MessageSquare,
} from "lucide-react";
import TopBar from "@/components/top-bar";
import GlassCard from "@/components/ui/glass-card";
import GlassButton from "@/components/ui/glass-button";
import {
  fetchOpportunities,
  fetchDashboardStats,
  fetchActivity,
} from "@/lib/api";
import type { ActivityItem } from "@/lib/api";
import { stateBadge, formatTimestamp } from "@/lib/shared";

export default function DashboardPage() {
  const router = useRouter();
  const [chatInput, setChatInput] = useState("");

  const { data: stats } = useSWR("dashboard-stats", fetchDashboardStats, {
    fallbackData: {
      total_opportunities: 0,
      total_approved: 0,
      active_topics: [],
      recent_score_avg: 0,
    },
    revalidateOnFocus: false,
  });

  const { data: oppData } = useSWR(
    "dashboard-opportunities",
    () => fetchOpportunities({ sort_by: "score", limit: 10 }),
    { fallbackData: { items: [], total: 0 }, revalidateOnFocus: false }
  );

  const { data: activity } = useSWR("dashboard-activity", fetchActivity, {
    fallbackData: [],
    revalidateOnFocus: false,
  });

  return (
    <div className="flex flex-col h-screen">
      <TopBar activeTab="dashboard" />

      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar */}
        <aside className="w-64 shrink-0 glass-panel backdrop-blur-xl border-r border-glass-border overflow-y-auto">
          <div className="p-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
              Recent Scans
            </h3>
            <ul className="space-y-1">
              <li className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-text-secondary">
                <span className="w-2 h-2 rounded-full bg-accent-green shrink-0" />
                <span className="flex-1 truncate">reddit.com</span>
                <span className="text-xs text-text-muted">2m ago</span>
              </li>
              <li className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-text-secondary">
                <span className="w-2 h-2 rounded-full bg-accent-green shrink-0" />
                <span className="flex-1 truncate">news.ycombinator.com</span>
                <span className="text-xs text-text-muted">5m ago</span>
              </li>
            </ul>
          </div>
        </aside>

        {/* Work Items Column */}
        <section className="w-[340px] shrink-0 border-r border-glass-border overflow-y-auto">
          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-text-primary">
                Work Items
              </h2>
              <button
                onClick={() => router.push("/work-items")}
                className="flex items-center gap-1 text-xs text-accent-purple hover:underline"
              >
                View all
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="space-y-3">
              {oppData && oppData.items.length > 0 ? (
                oppData.items.slice(0, 3).map((opp) => (
                  <GlassCard
                    key={opp.opportunity_id}
                    padding="p-4"
                    hover
                    onClick={() => router.push(`/work-items/${opp.opportunity_id}`)}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-text-primary truncate pr-2">
                        {opp.title}
                      </span>
                      {stateBadge(opp.state)}
                    </div>
                    <p className="text-xs text-text-muted mb-2 line-clamp-2">
                      {opp.enrichment_summary || opp.description}
                    </p>
                    <span className="font-mono text-accent-purple text-xs">
                      Score {Math.round(opp.opportunity_score)}/35
                    </span>
                  </GlassCard>
                ))
              ) : (
                <>
                  <GlassCard padding="p-4" hover onClick={() => router.push("/inbox")}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-text-primary truncate pr-2">
                        Restaurant Booking SaaS
                      </span>
                      {stateBadge("approved")}
                    </div>
                    <p className="text-xs text-text-muted mb-2 line-clamp-2">
                      AI-powered table management for independent restaurants
                    </p>
                    <span className="font-mono text-accent-purple text-xs">
                      Score 28/35
                    </span>
                  </GlassCard>
                  <GlassCard padding="p-4" hover onClick={() => router.push("/inbox")}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-text-primary truncate pr-2">
                        Dev Tool Analytics
                      </span>
                      {stateBadge("executing")}
                    </div>
                    <p className="text-xs text-text-muted mb-2 line-clamp-2">
                      Usage analytics dashboard for CLI tools
                    </p>
                    <span className="font-mono text-accent-purple text-xs">
                      Score 24/35
                    </span>
                  </GlassCard>
                </>
              )}
            </div>

            <div className="mt-6">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
                Recent Activity
              </h3>
              <div className="space-y-2">
                {(activity as ActivityItem[]).length > 0 ? (
                  (activity as ActivityItem[]).slice(0, 5).map((item, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-2 text-xs text-text-secondary"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-accent-purple mt-1.5 shrink-0" />
                      <span className="flex-1">{item.description}</span>
                      <span className="text-text-muted shrink-0">
                        {formatTimestamp(item.timestamp)}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-text-muted">
                    No recent activity yet.
                  </p>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Scout Inbox Column */}
        <section className="flex-1 border-r border-glass-border overflow-y-auto">
          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-text-primary">
                  Scout Inbox
                </h2>
                <span className="flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium rounded-full bg-accent-purple/15 text-accent-purple">
                  <Zap className="w-3 h-3" />3 new
                </span>
              </div>
              <button
                onClick={() => router.push("/inbox")}
                className="flex items-center gap-1 text-xs text-accent-purple hover:underline"
              >
                View more
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="space-y-3">
              {oppData?.items.length ? (
                oppData.items.map((opp, i) => (
                  <GlassCard
                    key={opp.opportunity_id}
                    padding="p-4"
                    className={i === 0 ? "bg-gradient-to-br from-accent-purple/[0.06] to-transparent" : ""}
                    hover
                    onClick={() => router.push(`/inbox/${opp.opportunity_id}`)}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-medium uppercase text-text-muted">
                        {opp.source_type || "opportunity"}
                      </span>
                      <span className="font-mono text-accent-purple text-xs">
                        {Math.round(opp.opportunity_score)}/35
                      </span>
                    </div>
                    <p className="text-sm font-medium text-text-primary mb-1 truncate">
                      {opp.title}
                    </p>
                    <p className="text-xs text-text-muted line-clamp-2">
                      {opp.enrichment_summary || opp.description}
                    </p>
                  </GlassCard>
                ))
              ) : (
                <div className="py-8 text-center text-sm text-text-muted">
                  No signals yet. Run a scout scan to get started.
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Right Column */}
        <aside className="w-96 shrink-0 overflow-y-auto">
          <div className="p-5 space-y-4 flex flex-col h-full">
            {/* Notification Toast */}
            <GlassCard
              padding="p-4"
              className="border-accent-purple/40"
            >
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-accent-purple/15 flex items-center justify-center shrink-0">
                  <Zap className="w-4 h-4 text-accent-purple" />
                </div>
                <div>
                  <p className="text-sm font-medium text-text-primary">
                    High-confidence opportunity found
                  </p>
                  <p className="text-xs text-text-muted mt-0.5">
                    Score 28/35 — Restaurant booking SaaS
                  </p>
                </div>
              </div>
            </GlassCard>

            {/* Quick Stats */}
            <GlassCard padding="p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
                Quick Stats
              </h3>
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="text-center">
                  <p className="text-2xl font-bold font-mono text-text-primary">
                    47
                  </p>
                  <p className="text-[11px] text-text-muted">Signals</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold font-mono text-text-primary">
                    8
                  </p>
                  <p className="text-[11px] text-text-muted">Opportunities</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold font-mono text-text-primary">
                    3
                  </p>
                  <p className="text-[11px] text-text-muted">Approved</p>
                </div>
              </div>
              <GlassButton
                variant="primary"
                className="w-full"
                onClick={() => router.push("/scout")}
              >
                <Radar className="w-4 h-4" />
                Run Scout
              </GlassButton>
            </GlassCard>

            {/* Chat with Foxhound */}
            <GlassCard padding="p-0" className="flex flex-col flex-1">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-glass-border">
                <MessageSquare className="w-4 h-4 text-accent-purple" />
                <h3 className="text-sm font-semibold text-text-primary">
                  Chat with Foxhound
                </h3>
              </div>

              <div className="flex-1 p-4 space-y-3 min-h-[280px]">
                <div className="flex items-start gap-2">
                  <div className="w-6 h-6 rounded-full bg-accent-purple/15 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-[10px] font-bold text-accent-purple">
                      F
                    </span>
                  </div>
                  <div className="bg-[rgba(255,255,255,0.03)] rounded-lg rounded-tl-none px-3 py-2">
                    <p className="text-xs text-text-secondary">
                      I found 3 new high-signal opportunities from your latest
                      scout run. Want me to summarize them?
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-2">
                  <div className="w-6 h-6 rounded-full bg-accent-purple/15 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-[10px] font-bold text-accent-purple">
                      F
                    </span>
                  </div>
                  <div className="bg-[rgba(255,255,255,0.03)] rounded-lg rounded-tl-none px-3 py-2">
                    <p className="text-xs text-text-secondary">
                      The restaurant booking SaaS scored 28/35 — strongest
                      signal I&apos;ve seen this week.
                    </p>
                  </div>
                </div>
              </div>

              <div className="px-4 pb-4">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="Ask Foxhound..."
                    className="flex-1 bg-[rgba(255,255,255,0.04)] border border-glass-border rounded-lg px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-purple/50"
                  />
                  <button className="w-8 h-8 rounded-lg bg-accent-purple flex items-center justify-center shrink-0 hover:opacity-90 transition-opacity">
                    <Send className="w-3.5 h-3.5 text-white" />
                  </button>
                </div>
              </div>
            </GlassCard>
          </div>
        </aside>
      </div>
    </div>
  );
}
