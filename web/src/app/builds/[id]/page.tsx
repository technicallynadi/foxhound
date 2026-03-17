"use client";

import { use } from "react";
import useSWR from "swr";
import { Check, Loader, Circle } from "lucide-react";
import TopBar from "@/components/top-bar";
import GlassTerminal from "@/components/ui/glass-terminal";
import type { TerminalLine } from "@/components/ui/glass-terminal";
import { fetchOpportunity } from "@/lib/api";

const HARNESS_STEPS = [
  {
    name: "validate_input",
    desc: "Task envelope validated — recipe: one_shot",
    status: "done" as const,
  },
  {
    name: "build_context",
    desc: "Context pack assembled — 12 files, trust labels applied",
    status: "done" as const,
  },
  {
    name: "execute",
    desc: "Running execution worker — balanced tier model",
    status: "active" as const,
  },
  {
    name: "sanitize_output",
    desc: "Pending — strip dangerous patterns, redact secrets",
    status: "pending" as const,
  },
  {
    name: "evaluate_output",
    desc: "Pending — grounding, confidence, and safety checks",
    status: "pending" as const,
  },
  {
    name: "finalize",
    desc: "Pending — emit result envelope, events, artifacts",
    status: "pending" as const,
  },
];

function buildTerminalLines(title: string): TerminalLine[] {
  return [
    { text: `$ foxhound run run-0042`, color: "purple" },
    { text: "" },
    { text: "  [harness] validate_input \u2713  recipe: one_shot", color: "green" },
    { text: "  [harness] build_context \u2713  12 files, 3 trust tiers applied", color: "green" },
    { text: "  [harness] execute \u25C9  running execution worker...", color: "purple" },
    { text: "" },
    { text: "  [workspace] Creating isolated worktree...", color: "secondary" },
    { text: `  [workspace] Branch: foxhound/42-${title.toLowerCase().replace(/\s+/g, "-").slice(0, 30)}`, color: "secondary" },
    { text: "  [context]   Loaded context pack (semi-trusted: repo files)", color: "secondary" },
    { text: "" },
    { text: "  [execute]   Generating project scaffold...", color: "primary" },
    { text: "  [execute]   \u2713 Created src/app/models.py", color: "green" },
    { text: "  [execute]   \u2713 Created src/app/api.py", color: "green" },
    { text: "  [execute]   \u2713 Created src/app/scheduler.py", color: "green" },
    { text: "  [execute]   \u2713 Created tests/test_app.py", color: "green" },
    { text: "" },
    { text: "  [validate]  Running: pytest tests/", color: "secondary" },
    { text: "  [validate]  \u2713 8 passed, 0 failed", color: "green" },
    { text: "  [validate]  Running: mypy src/", color: "secondary" },
    { text: "  [validate]  \u2713 No type errors found", color: "green" },
    { text: "" },
    { text: "  [execute]   Generating landing page copy...", color: "secondary" },
  ];
}

export default function BuildExecutionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: opp } = useSWR(
    id ? `build-${id}` : null,
    () => fetchOpportunity(id)
  );

  const title = opp?.title ?? "Build";
  const terminalLines = buildTerminalLines(title);

  return (
    <div className="min-h-screen">
      <TopBar activeTab="builds" />

      <div className="flex min-h-[calc(100vh-52px)]">
        <aside className="w-[420px] shrink-0 glass-panel backdrop-blur-xl border-r border-glass-border p-7 space-y-6">
          <div className="space-y-2">
            <p className="text-xs font-semibold text-text-muted tracking-wider">
              EXECUTION RUN
            </p>
            <h1 className="text-[22px] font-bold text-text-primary">{title}</h1>
            <div className="flex items-center gap-3">
              <span className="font-mono text-xs font-medium text-accent-purple">
                run-0042
              </span>
              <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-accent-green/[0.12] text-accent-green">
                EXECUTING
              </span>
            </div>
          </div>

          <div className="h-px bg-glass-border" />

          <div>
            <h3 className="text-sm font-semibold text-text-primary mb-5">
              Harness Pipeline
            </h3>
            <div className="space-y-5">
              {HARNESS_STEPS.map((step) => (
                <div key={step.name} className="flex items-start gap-3">
                  <div
                    className={`flex items-center justify-center w-7 h-7 rounded-full shrink-0 ${
                      step.status === "done"
                        ? "bg-accent-green/[0.12]"
                        : step.status === "active"
                          ? "bg-accent-purple/[0.12]"
                          : "bg-[rgba(255,255,255,0.03)]"
                    }`}
                  >
                    {step.status === "done" ? (
                      <Check className="w-3.5 h-3.5 text-accent-green" />
                    ) : step.status === "active" ? (
                      <Loader className="w-3.5 h-3.5 text-accent-purple animate-spin" />
                    ) : (
                      <Circle className="w-2 h-2 text-text-muted fill-text-muted" />
                    )}
                  </div>
                  <div>
                    <p
                      className={`font-mono text-[13px] ${
                        step.status === "active"
                          ? "text-accent-purple font-semibold"
                          : step.status === "done"
                            ? "text-text-primary font-medium"
                            : "text-text-muted"
                      }`}
                    >
                      {step.name}
                    </p>
                    <p className="text-xs text-text-muted mt-0.5">
                      {step.desc}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>

        <main className="flex-1 p-7 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-text-primary">
              Execution Output
            </h2>
            <div className="flex items-center gap-4">
              <span className="font-mono text-xs text-text-muted">
                Cost: $0.12
              </span>
              <span className="font-mono text-xs text-text-muted">
                Tokens: 14,200
              </span>
              <span className="font-mono text-xs text-accent-purple">
                balanced
              </span>
            </div>
          </div>

          <GlassTerminal
            title={`foxhound run run-0042 — isolated workspace`}
            lines={terminalLines}
            showCursor
          />
        </main>
      </div>
    </div>
  );
}
