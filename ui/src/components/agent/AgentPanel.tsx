"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAgent } from "./AgentProvider";
import MessageList from "./MessageList";
import ChatInput from "./ChatInput";
import { getActivityFeed } from "@/lib/api";

const SIZES = {
  default: { width: 400, height: 560 },
  expanded: { width: 560, height: 640 },
} as const;

type PanelSize = keyof typeof SIZES;

export default function AgentPanel() {
  const { messages, streamState, send, close, loadHistory, draft, setDraft } =
    useAgent();
  const [size, setSize] = useState<PanelSize>("default");

  useEffect(() => {
    if (messages.length === 0) loadHistory();
  }, [loadHistory, messages.length]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [close]);

  // Auto-expand when tool results contain rich content
  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role === "assistant" && lastMsg.toolName) {
      const richTools = [
        "apply_to_job",
        "get_dossier",
        "interview_prep",
        "discover_jobs",
      ];
      if (richTools.includes(lastMsg.toolName)) {
        const timer = window.setTimeout(() => setSize("expanded"), 0);
        return () => window.clearTimeout(timer);
      }
    }
  }, [messages]);

  const { width, height } = SIZES[size];

  return (
    <div
      role="dialog"
      aria-label="Foxhound"
      aria-modal="false"
      className="agent-panel"
      style={{
        width,
        height,
        maxHeight: "80vh",
        display: "flex",
        flexDirection: "column",
        background: "rgba(14, 14, 14, 0.9)",
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        border: "1px solid var(--bv)",
        borderRadius: 16,
        boxShadow:
          "0 24px 64px rgba(0,0,0,0.7), 0 0 48px rgba(139,92,246,0.06)",
        overflow: "hidden",
        animation: "panel-open 250ms cubic-bezier(0.34, 1.56, 0.64, 1)",
        transformOrigin: "bottom right",
        transition:
          "width 300ms cubic-bezier(0.4, 0, 0.2, 1), height 300ms cubic-bezier(0.4, 0, 0.2, 1)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "11px 16px",
          borderBottom: "1px solid var(--b)",
          flexShrink: 0,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--t3)",
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--v)",
            boxShadow: "0 0 6px var(--v)",
            animation: "status-pulse 2s infinite",
          }}
        />
        FOXHOUND
        {/* Size toggle */}
        {size === "expanded" && (
          <button
            onClick={() => setSize("default")}
            aria-label="Collapse panel"
            style={{
              background: "none",
              border: "none",
              color: "var(--t3)",
              cursor: "pointer",
              fontSize: 14,
              lineHeight: 1,
              padding: "0 4px",
              marginLeft: 4,
            }}
          >
            &#8592;
          </button>
        )}
        <span
          style={{
            marginLeft: "auto",
            color: streamState !== "idle" ? "var(--vl)" : "var(--g)",
          }}
        >
          {streamState !== "idle" ? "WORKING..." : "ACTIVE"}
        </span>
      </div>

      {/* Notification banner — pending items */}
      <PanelNotifications messages={messages} />

      <MessageList
        messages={messages}
        streamState={streamState}
        onSend={send}
      />

      <ChatInput
        onSend={send}
        placeholder="Ask Foxhound anything..."
        value={draft}
        onChange={setDraft}
      />

      <style jsx>{`
        @keyframes panel-open {
          from {
            opacity: 0;
            transform: scale(0.9) translateY(8px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
        @media (max-width: 768px) {
          .agent-panel {
            width: 100vw !important;
            height: 70vh !important;
            max-height: 70vh !important;
            border-radius: 16px 16px 0 0 !important;
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            right: 0 !important;
            top: auto !important;
          }
        }
      `}</style>
    </div>
  );
}

/* ─── Panel notification banner ─── */

interface AgentMsg {
  role: string;
  toolName?: string;
  toolResult?: Record<string, unknown>;
}

function PanelNotifications({ messages }: { messages: AgentMsg[] }) {
  type BannerType = "question" | "brief" | "alert";
  type BannerItem = {
    label: string;
    type: BannerType;
    href?: string;
    priority: 0 | 1 | 2;
  };
  const pendingItems: BannerItem[] = [];
  const [activityItems, setActivityItems] = useState<BannerItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    void getActivityFeed(1, 6)
      .then((data) => {
        if (cancelled) return;
        const items = (data.events || [])
          .filter((event) =>
            [
              "questions_pending",
              "research_completed",
              "dossier_ready",
              "followup_reminder",
              "application_blocked",
              "ghost_alert",
              "interview_detected",
            ].includes(event.type),
          )
          .slice(0, 4)
          .map((event) => ({
            label: event.title,
            type:
              event.type === "questions_pending" ||
              event.type === "application_blocked"
                ? ("question" as const)
                : event.type === "followup_reminder" ||
                    event.type === "ghost_alert" ||
                    event.type === "interview_detected"
                  ? ("alert" as const)
                  : ("brief" as const),
            href: event.metadata?.application_id
              ? `/brief/${String(event.metadata.application_id)}`
              : undefined,
            priority:
              event.type === "questions_pending" ||
              event.type === "application_blocked" ||
              event.type === "followup_reminder" ||
              event.type === "ghost_alert" ||
              event.type === "interview_detected"
                ? (0 as const)
                : (1 as const),
          }));
        setActivityItems(items);
      })
      .catch(() => {
        if (!cancelled) setActivityItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [messages.length]);  // Only re-fetch when message count changes, not on every token

  for (const msg of messages.slice(-10)) {
    if (msg.role !== "assistant" || !msg.toolResult) continue;
    const r = msg.toolResult;
    const action =
      r.recommended_next_action && typeof r.recommended_next_action === "object"
        ? (r.recommended_next_action as Record<string, unknown>)
        : null;

    if (action && typeof action.label === "string" && action.label) {
      const href = typeof action.href === "string" ? action.href : undefined;
      const priority: 0 | 1 | 2 =
        action.priority === "high" ? 0 : action.priority === "low" ? 2 : 1;
      pendingItems.push({
        label: action.label,
        type: priority === 0 ? "alert" : "brief",
        href,
        priority,
      });
    }

    // Pending questions
    if (msg.toolName === "apply_to_job" && r.status === "waiting_user_input") {
      const count = Array.isArray(r.pending_questions)
        ? r.pending_questions.length
        : 0;
      if (count > 0) {
        pendingItems.push({
          label: `${r.company || "Application"} — ${count} question${count !== 1 ? "s" : ""} pending`,
          type: "question",
          priority: 0,
        });
      }
    }

    // Brief ready (from research cascade events)
    if (msg.toolName === "get_dossier" && r.status === "ready") {
      pendingItems.push({
        label: `Brief ready: ${r.company || "application"}`,
        type: "brief",
        href: r.dossier_id ? `/brief/${r.application_id || ""}` : undefined,
        priority: 1,
      });
    }
  }

  const mergedItems = [...pendingItems, ...activityItems]
    .filter(
      (item, index, all) =>
        all.findIndex(
          (candidate) =>
            candidate.label === item.label && candidate.href === item.href,
        ) === index,
    )
    .sort((a, b) => a.priority - b.priority)
    .slice(0, 4);

  if (mergedItems.length === 0) return null;

  return (
    <div
      style={{
        background: "var(--el)",
        border: "1px solid var(--bv)",
        borderRadius: 8,
        margin: 8,
        padding: "8px 12px",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--t3)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 6,
        }}
      >
        {mergedItems.length} priority item{mergedItems.length !== 1 ? "s" : ""}
      </div>
      {mergedItems.map((item, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "3px 0",
            fontSize: 12,
            color: "var(--t2)",
          }}
        >
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              flexShrink: 0,
              background:
                item.type === "question"
                  ? "var(--warning)"
                  : item.type === "alert"
                    ? "var(--error)"
                    : "var(--vl)",
              animation:
                item.priority === 0 ? "status-pulse 2s infinite" : "none",
            }}
          />
          {item.href ? (
            <Link href={item.href} style={{ color: "var(--vl)", fontSize: 12 }}>
              {item.label}
            </Link>
          ) : (
            <span>{item.label}</span>
          )}
        </div>
      ))}
    </div>
  );
}
