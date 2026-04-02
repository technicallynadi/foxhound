"use client";

import { useAgent } from "./AgentProvider";

export default function AgentFAB() {
  const { toggle, streamState, hasNotification, notificationCount } =
    useAgent();
  const isWorking =
    streamState === "streaming" || streamState === "tool_executing";

  return (
    <button
      onClick={toggle}
      aria-label="Open Foxhound"
      className="agent-fab"
      data-working={isWorking}
      style={{
        width: 52,
        height: 52,
        borderRadius: "50%",
        border: "none",
        background: "linear-gradient(135deg, var(--v), var(--vd))",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        position: "relative",
        transition:
          "transform 180ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 180ms ease-out",
        boxShadow:
          "0 4px 20px rgba(139,92,246,0.25), 0 0 40px rgba(139,92,246,0.08)",
      }}
    >
      {/* Foxhound icon — violet dot with signal rings */}
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="4" fill="white" />
        <circle
          cx="12"
          cy="12"
          r="8"
          stroke="white"
          strokeWidth="1.5"
          opacity="0.5"
        />
        <circle
          cx="12"
          cy="12"
          r="11"
          stroke="white"
          strokeWidth="1"
          opacity="0.25"
        />
      </svg>

      {hasNotification && (
        <span
          style={{
            position: "absolute",
            top: -2,
            right: -2,
            minWidth: 18,
            height: 18,
            borderRadius: 9,
            background: "var(--error)",
            border: "2px solid var(--bg)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 700,
            color: "#fff",
            animation: "status-pulse 2s ease-in-out infinite",
            padding: "0 4px",
          }}
        >
          {notificationCount > 0 ? Math.min(notificationCount, 9) : ""}
        </span>
      )}

      <style jsx>{`
        .agent-fab:hover {
          transform: scale(1.08);
          box-shadow:
            0 4px 24px rgba(139, 92, 246, 0.35),
            0 0 48px rgba(139, 92, 246, 0.12);
        }
        .agent-fab:active {
          transform: scale(0.96);
        }
        .agent-fab:focus-visible {
          outline: 2px solid var(--v);
          outline-offset: 4px;
        }
        .agent-fab[data-working="true"]::before {
          content: "";
          position: absolute;
          inset: -4px;
          border-radius: 50%;
          background: conic-gradient(
            from 0deg,
            var(--v),
            var(--vd),
            transparent 70%
          );
          animation: ring-orbit 1.5s linear infinite;
          z-index: -1;
        }
        .agent-fab[data-working="true"]::after {
          content: "";
          position: absolute;
          inset: -2px;
          border-radius: 50%;
          background: var(--bg);
          z-index: -1;
        }
        @keyframes ring-orbit {
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </button>
  );
}
