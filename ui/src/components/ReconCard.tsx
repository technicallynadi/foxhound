"use client";

import { useEffect, useRef } from "react";
import { useRecon } from "@/hooks/useRecon";
import type {
  ReconSectionStatus,
} from "@/hooks/useRecon";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ReconCardProps {
  jobId: string;
  companyName: string;
  jobTitle?: string;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Shimmer skeleton block — mirrors PageSkeleton pattern */
function ShimmerBlock({ w, h }: { w?: string | number; h: number }) {
  return (
    <div
      className="recon-skel"
      style={{
        width: w ?? "100%",
        height: h,
        borderRadius: 4,
        background: "var(--sf)",
        position: "relative",
        overflow: "hidden",
      }}
    />
  );
}

/** Section wrapper with numbered monospace label and reveal animation */
function Section({
  index,
  label,
  status,
  children,
}: {
  index: number;
  label: string;
  status: ReconSectionStatus;
  children: React.ReactNode;
}) {
  const padded = String(index).padStart(2, "0");
  const isReady = status === "done" || status === "error";

  return (
    <div
      className="recon-section"
      style={{
        opacity: isReady ? 1 : 0.5,
        transform: isReady ? "translateY(0)" : "translateY(6px)",
        transition: "opacity 0.45s ease-out, transform 0.45s ease-out",
      }}
    >
      {/* Section label */}
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          fontWeight: 500,
          color: "var(--vl)",
          letterSpacing: "0.15em",
          textTransform: "uppercase",
          marginBottom: 10,
        }}
      >
        {padded} / {label}
      </div>

      {/* Content or shimmer */}
      {status === "loading" || status === "idle" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <ShimmerBlock h={14} w="80%" />
          <ShimmerBlock h={12} w="55%" />
          <ShimmerBlock h={12} w="65%" />
        </div>
      ) : (
        children
      )}
    </div>
  );
}

/** Muted error fallback */
function Unavailable() {
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--t3)",
        letterSpacing: "0.04em",
      }}
    >
      Data unavailable
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

function TechStackSection({ technologies }: { technologies: string[] }) {
  if (!technologies || technologies.length === 0) {
    return <Unavailable />;
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {technologies.map((tech) => (
        <span
          key={tech}
          style={{
            display: "inline-block",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            fontWeight: 500,
            color: "var(--vl)",
            background: "var(--vf)",
            border: "1px solid var(--bv)",
            borderRadius: 4,
            padding: "3px 8px",
            letterSpacing: "0.02em",
          }}
        >
          {tech}
        </span>
      ))}
    </div>
  );
}

export default function ReconCard({
  jobId,
  companyName,
  jobTitle,
  onClose,
}: ReconCardProps) {
  const { state, start, abort } = useRecon();
  const startedRef = useRef(false);

  // Auto-start recon when mounted
  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true;
      start(jobId);
    }
    return () => {
      abort();
    };
  }, [abort, jobId, start]);

  // Merge tech stacks: careers.technologies + synthesis.tech_stack, deduplicated
  const techStack = (() => {
    const set = new Set<string>();
    if (state.careers.data?.technologies) {
      state.careers.data.technologies.forEach((t) => set.add(t));
    }
    if (state.synthesis.data?.tech_stack) {
      state.synthesis.data.tech_stack.forEach((t) => set.add(t));
    }
    // Fallback to posting tech_stack
    if (set.size === 0 && state.posting.data?.tech_stack) {
      state.posting.data.tech_stack.forEach((t) => set.add(t));
    }
    return Array.from(set);
  })();

  const isActive =
    state.overall === "connecting" || state.overall === "streaming";

  return (
    <div
      className="recon-overlay"
      onClick={onClose}
      role="dialog"
      aria-label={`Quick Report for ${companyName}`}
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "rgba(0, 0, 0, 0.72)",
        backdropFilter: "blur(10px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="recon-card"
        style={{
          background: "var(--bg)",
          border: "1px solid var(--b)",
          borderLeft: "3px solid var(--v)",
          borderRadius: 12,
          maxWidth: 600,
          width: "100%",
          maxHeight: "85vh",
          overflow: "auto",
          padding: 0,
          animation: "recon-enter 0.25s ease-out",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "20px 24px 16px",
            borderBottom: "1px solid var(--b)",
            display: "flex",
            alignItems: "start",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--vl)",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                marginBottom: 6,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              QUICK REPORT
              {isActive && (
                <span
                  className="recon-pulse"
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: "var(--v)",
                    display: "inline-block",
                  }}
                />
              )}
              {state.overall === "done" && state.cached && (
                <span
                  style={{
                    color: "var(--t3)",
                    fontSize: 9,
                    letterSpacing: "0.08em",
                  }}
                >
                  CACHED
                </span>
              )}
            </div>
            <h2
              style={{
                fontFamily: "var(--font-display)",
                fontSize: 20,
                fontWeight: 700,
                letterSpacing: "-0.02em",
                color: "var(--t)",
                textTransform: "uppercase",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {companyName}
            </h2>
            {jobTitle && (
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: "var(--t3)",
                  letterSpacing: "0.04em",
                  marginTop: 2,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {jobTitle}
              </div>
            )}
          </div>

          <button
            onClick={onClose}
            aria-label="Close quick report"
            style={{
              width: 32,
              height: 32,
              minWidth: 32,
              borderRadius: 8,
              border: "none",
              background: "rgba(255, 255, 255, 0.04)",
              color: "var(--t3)",
              cursor: "pointer",
              fontSize: 16,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "background 0.2s",
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "rgba(255, 255, 255, 0.08)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "rgba(255, 255, 255, 0.04)";
            }}
          >
            &times;
          </button>
        </div>

        {/* Body — sections (all driven by synthesis data from job description) */}
        <div
          style={{
            padding: "20px 24px 24px",
            display: "flex",
            flexDirection: "column",
            gap: 24,
          }}
        >
          {/* 01 / COMPANY */}
          <Section
            index={1}
            label="COMPANY"
            status={
              state.synthesis.status === "done"
                ? "done"
                : state.synthesis.status === "loading" ||
                    state.overall === "streaming"
                  ? "loading"
                  : "error"
            }
          >
            {state.synthesis.data?.summary ? (
              <div
                style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.6 }}
              >
                {state.synthesis.data.summary}
                {state.posting.data && (
                  <div
                    style={{
                      display: "flex",
                      gap: 12,
                      flexWrap: "wrap",
                      marginTop: 10,
                    }}
                  >
                    {state.posting.data.location && (
                      <span
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 10,
                          color: "var(--t3)",
                          letterSpacing: "0.04em",
                        }}
                      >
                        {String(state.posting.data.location)}
                      </span>
                    )}
                    {state.posting.data.remote_type && (
                      <span
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 10,
                          color: "var(--vl)",
                          letterSpacing: "0.04em",
                        }}
                      >
                        {String(state.posting.data.remote_type)}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ) : null}
          </Section>

          {/* Divider */}
          <div
            style={{
              height: 1,
              background:
                "linear-gradient(90deg, transparent, rgba(139, 92, 246, 0.12), transparent)",
            }}
          />

          {/* 02 / HIRING */}
          <Section
            index={2}
            label="HIRING"
            status={
              state.synthesis.status === "done"
                ? "done"
                : state.synthesis.status === "loading" ||
                    state.overall === "streaming"
                  ? "loading"
                  : "error"
            }
          >
            {state.synthesis.data ? (
              <div>
                {state.synthesis.data.hiring_velocity && (
                  <div
                    style={{
                      fontSize: 13,
                      color: "var(--t2)",
                      lineHeight: 1.6,
                    }}
                  >
                    {state.synthesis.data.hiring_velocity}
                  </div>
                )}
                {state.synthesis.data.team_insight && (
                  <div
                    style={{
                      fontSize: 12,
                      color: "var(--t3)",
                      marginTop: 6,
                      lineHeight: 1.5,
                    }}
                  >
                    {state.synthesis.data.team_insight}
                  </div>
                )}
              </div>
            ) : null}
          </Section>

          {/* Divider */}
          <div
            style={{
              height: 1,
              background:
                "linear-gradient(90deg, transparent, rgba(139, 92, 246, 0.12), transparent)",
            }}
          />

          {/* 03 / TECH STACK */}
          <Section
            index={3}
            label="TECH STACK"
            status={
              state.synthesis.status === "done"
                ? "done"
                : state.synthesis.status === "loading" ||
                    state.overall === "streaming"
                  ? "loading"
                  : "error"
            }
          >
            {techStack.length > 0 ? (
              <TechStackSection technologies={techStack} />
            ) : state.synthesis.status === "done" ? (
              <Unavailable />
            ) : null}
          </Section>

          {/* Divider */}
          <div
            style={{
              height: 1,
              background:
                "linear-gradient(90deg, transparent, rgba(139, 92, 246, 0.12), transparent)",
            }}
          />

          {/* 04 / INSIDER TIP */}
          <Section
            index={4}
            label="INSIDER TIP"
            status={
              state.synthesis.status === "done"
                ? "done"
                : state.synthesis.status === "loading" ||
                    state.overall === "streaming"
                  ? "loading"
                  : "error"
            }
          >
            {state.synthesis.data?.insider_tip ? (
              <div
                style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.6 }}
              >
                {state.synthesis.data.insider_tip}
              </div>
            ) : null}
          </Section>

          {/* Duration footer */}
          {state.overall === "done" && state.durationMs !== null && (
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--t3)",
                letterSpacing: "0.06em",
                textAlign: "right",
                marginTop: 4,
              }}
            >
              {state.cached
                ? "cached"
                : `${(state.durationMs / 1000).toFixed(1)}s`}
            </div>
          )}

          {/* Overall error state */}
          {state.overall === "error" && (
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--error, #F87171)",
                letterSpacing: "0.04em",
                textAlign: "center",
                padding: "12px 0",
              }}
            >
              {state.errorMessage || "Quick report failed. Try again later."}
            </div>
          )}
        </div>
      </div>

      {/* Scoped styles */}
      <style>{`
        .recon-skel {
          position: relative;
          overflow: hidden;
        }
        .recon-skel::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.04) 40%,
            rgba(255, 255, 255, 0.06) 50%,
            rgba(255, 255, 255, 0.04) 60%,
            transparent 100%
          );
          animation: recon-shimmer 1.8s ease-in-out infinite;
        }
        @keyframes recon-shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
        @keyframes recon-enter {
          from {
            opacity: 0;
            transform: scale(0.96) translateY(8px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
        @keyframes recon-pulse-glow {
          0%, 100% { opacity: 1; box-shadow: 0 0 4px var(--v); }
          50% { opacity: 0.4; box-shadow: 0 0 8px var(--v); }
        }
        .recon-pulse {
          animation: recon-pulse-glow 1.2s ease-in-out infinite;
        }
        .recon-card {
          scrollbar-width: thin;
          scrollbar-color: var(--el) transparent;
        }
        .recon-card::-webkit-scrollbar {
          width: 6px;
        }
        .recon-card::-webkit-scrollbar-track {
          background: transparent;
        }
        .recon-card::-webkit-scrollbar-thumb {
          background: var(--el);
          border-radius: 3px;
        }

        @media (max-width: 480px) {
          .recon-card {
            max-width: calc(100vw - 24px) !important;
            border-radius: 10px !important;
          }
        }
        @media (max-width: 768px) {
          .recon-card {
            max-width: calc(100vw - 32px) !important;
          }
        }

        @media (prefers-reduced-motion: reduce) {
          .recon-skel::after {
            animation: none;
          }
          .recon-pulse {
            animation: none;
          }
          .recon-card {
            animation: none !important;
          }
          .recon-section {
            transition: none !important;
          }
        }
      `}</style>
    </div>
  );
}
