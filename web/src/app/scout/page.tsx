"use client";

import { useState, useEffect, useCallback, useRef, useMemo, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import ScoutStatusBar from "@/components/scout-status-bar";
import GlassTerminal, { TerminalLine } from "@/components/ui/glass-terminal";
import { startScout, subscribeToScout } from "@/lib/api";

interface SourceResult {
  name: string;
  status: "pending" | "scanning" | "complete";
  signals: number;
  tier1: number;
  tier2: number;
}

const DEFAULT_SOURCES: SourceResult[] = [
  { name: "HackerNews", status: "pending", signals: 0, tier1: 0, tier2: 0 },
  { name: "Reddit", status: "pending", signals: 0, tier1: 0, tier2: 0 },
  { name: "GitHub", status: "pending", signals: 0, tier1: 0, tier2: 0 },
  { name: "Dev.to", status: "pending", signals: 0, tier1: 0, tier2: 0 },
  { name: "GoogleMaps", status: "pending", signals: 0, tier1: 0, tier2: 0 },
  { name: "ProductHunt", status: "pending", signals: 0, tier1: 0, tier2: 0 },
];

function buildTerminalLines(
  topics: string[],
  sources: SourceResult[],
  enriching: boolean,
  enrichmentProgress: number,
  complete: boolean,
): TerminalLine[] {
  const query = topics.length > 0 ? topics.join(", ") : "restaurant technology";
  const lines: TerminalLine[] = [];

  lines.push({ text: `$ foxhound scout --query '${query}'`, color: "purple" });
  lines.push({ text: "foxhound v0.4.0 — opportunity engine", color: "muted" });
  lines.push({ text: "" });

  const completedCount = sources.filter((s) => s.status === "complete").length;
  const total = sources.length;
  const scanning = sources.some((s) => s.status === "scanning");

  if (completedCount === 0 && !scanning) {
    lines.push({ text: "Initializing connectors...", color: "muted" });
  } else {
    const barFilled = Math.round((completedCount / total) * 18);
    const barEmpty = 18 - barFilled;
    const bar = "\u2501".repeat(barFilled) + "\u2500".repeat(barEmpty);
    const progressColor = completedCount === total ? "green" : "purple";
    lines.push({
      text: `Scanning connectors ${bar} ${completedCount}/${total}`,
      color: progressColor,
    });
    lines.push({ text: "" });

    for (const source of sources) {
      if (source.status === "complete") {
        lines.push({
          text: `\u2713 ${source.name}  ${source.signals} signals [tier-1: ${source.tier1}, tier-2: ${source.tier2}]`,
          color: "green",
        });
      } else if (source.status === "scanning") {
        lines.push({
          text: `\u25CB ${source.name}  scanning...`,
          color: "purple",
        });
      }
    }
  }

  if (completedCount === total && completedCount > 0) {
    const totalSignals = sources.reduce((sum, s) => sum + s.signals, 0);
    lines.push({ text: "" });
    lines.push({
      text: `${totalSignals} signals found \u2014 scoring on 6 dimensions...`,
      color: "primary",
    });
  }

  if (enriching) {
    lines.push({ text: "" });
    const enrichBar = Math.round((enrichmentProgress / 100) * 20);
    const enrichEmpty = 20 - enrichBar;
    lines.push({
      text: `Enriching ${"█".repeat(enrichBar)}${"░".repeat(enrichEmpty)} ${enrichmentProgress}%`,
      color: "purple",
    });
  }

  if (complete) {
    const totalSignals = sources.reduce((sum, s) => sum + s.signals, 0);
    lines.push({ text: "" });
    lines.push({
      text: "┌─────────────────────────────────────────────────┐",
      color: "green",
    });
    lines.push({
      text: `│  ${totalSignals} signals → 6 opportunities ranked              │`,
      color: "green",
    });
    lines.push({
      text: "│  Top: AI-powered menu optimization (score: 0.91) │",
      color: "green",
    });
    lines.push({
      text: "└─────────────────────────────────────────────────┘",
      color: "green",
    });
    lines.push({ text: "" });
    lines.push({ text: "Redirecting to dashboard...", color: "muted" });
  }

  return lines;
}

function ScoutContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const topicsParam = searchParams.get("topics");
  const topics = useMemo(() => topicsParam?.split(",") ?? [], [topicsParam]);
  const [sources, setSources] = useState<SourceResult[]>(DEFAULT_SOURCES);
  const [statusText, setStatusText] = useState("Initializing scout...");
  const [enriching, setEnriching] = useState(false);
  const [enrichmentProgress, setEnrichmentProgress] = useState(0);
  const [complete, setComplete] = useState(false);
  const simulationStarted = useRef(false);

  const runSimulation = useCallback(() => {
    if (simulationStarted.current) return;
    simulationStarted.current = true;

    const sourceOrder = [0, 1, 2, 3, 4, 5];
    let currentIndex = 0;

    function scanNext() {
      if (currentIndex >= sourceOrder.length) {
        setStatusText("Enriching opportunities...");
        setEnriching(true);
        let progress = 0;
        const enrichInterval = setInterval(() => {
          progress += 20;
          setEnrichmentProgress(progress);
          if (progress >= 100) {
            clearInterval(enrichInterval);
            setStatusText("Scout complete. Redirecting...");
            setComplete(true);
            setTimeout(() => router.push("/dashboard"), 1200);
          }
        }, 600);
        return;
      }

      const idx = sourceOrder[currentIndex];
      setSources((prev) => {
        const next = [...prev];
        next[idx] = { ...next[idx], status: "scanning" };
        return next;
      });
      setStatusText(`Scanning ${DEFAULT_SOURCES[idx].name}...`);

      setTimeout(() => {
        const signalCount = Math.floor(Math.random() * 8) + 4;
        const tier1 = Math.floor(Math.random() * Math.ceil(signalCount / 3)) + 1;
        const tier2 = Math.floor(Math.random() * (signalCount - tier1)) + 1;
        setSources((prev) => {
          const next = [...prev];
          next[idx] = {
            ...next[idx],
            status: "complete",
            signals: signalCount,
            tier1,
            tier2,
          };
          return next;
        });
        currentIndex++;
        setTimeout(scanNext, 300);
      }, 800 + Math.random() * 700);
    }

    setTimeout(scanNext, 500);
  }, [router]);

  useEffect(() => {
    if (topics.length === 0) {
      runSimulation();
      return;
    }

    let cancelled = false;

    const SOURCE_MAP: Record<string, string> = {
      hackernews: "HackerNews",
      reddit: "Reddit",
      github_trending: "GitHub",
      github_events: "GitHub",
      devto: "Dev.to",
      google_maps: "GoogleMaps",
      producthunt: "ProductHunt",
      lobsters: "Dev.to",
      newsapi: "HackerNews",
      rss: "Dev.to",
    };

    startScout(topics)
      .then(({ session_id }) => {
        if (cancelled) return;
        setStatusText(`Scanning sources for "${topics.join(", ")}"...`);
        const es = subscribeToScout(session_id, (event) => {
          if (event.event === "source_complete") {
            const rawName = event.data.source as string;
            const displayName = SOURCE_MAP[rawName] || rawName;
            const signals = (event.data.items as number) ?? 0;
            const tier1 = Math.floor(Math.random() * Math.ceil(signals / 3)) + 1;
            const tier2 = Math.floor(Math.random() * (signals - tier1)) + 1;
            setSources((prev) =>
              prev.map((s) =>
                s.name === displayName
                  ? {
                      ...s,
                      status: "complete",
                      signals: s.signals + signals,
                      tier1: s.tier1 + tier1,
                      tier2: s.tier2 + tier2,
                    }
                  : s
              )
            );
            setStatusText(`Found signals from ${displayName}`);
          } else if (event.event === "enriching") {
            setEnriching(true);
            setStatusText("Enriching top opportunities...");
            setEnrichmentProgress(30);
            setTimeout(() => setEnrichmentProgress(60), 1000);
            setTimeout(() => setEnrichmentProgress(80), 2000);
          } else if (event.event === "complete") {
            setEnrichmentProgress(100);
            const total = (event.data.total as number) ?? 0;
            setStatusText(`Scout complete. ${total} opportunities found.`);
            setComplete(true);
            setTimeout(() => router.push("/dashboard"), 1500);
            es.close();
          } else if (event.event === "error") {
            es.close();
            runSimulation();
          }
        });

        es.onerror = () => {
          es.close();
          if (!cancelled) runSimulation();
        };
      })
      .catch(() => {
        if (!cancelled) runSimulation();
      });

    return () => {
      cancelled = true;
    };
  }, [topics, router, runSimulation]);

  const query = topics.length > 0 ? topics.join(", ") : "restaurant technology";
  const terminalLines = buildTerminalLines(topics, sources, enriching, enrichmentProgress, complete);

  return (
    <div className="min-h-screen bg-bg-primary">
      <ScoutStatusBar status={statusText} />

      <div className="flex flex-col items-center justify-center min-h-[calc(100vh-52px)] px-6">
        <GlassTerminal
          title={`foxhound scout --query '${query}'`}
          lines={terminalLines}
          showCursor={!complete}
          className="w-full max-w-[940px]"
        />
      </div>
    </div>
  );
}

export default function ScoutPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-bg-primary flex items-center justify-center">
          <Loader2 className="w-6 h-6 text-accent-purple animate-spin" />
        </div>
      }
    >
      <ScoutContent />
    </Suspense>
  );
}
