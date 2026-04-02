"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

interface Message {
  type: "agent" | "user" | "typing" | "break";
  content?: ReactNode;
  delay: number;
}

const MESSAGES: Message[] = [
  { type: "typing", delay: 500 },
  {
    type: "agent",
    delay: 1200,
    content: (
      <>
        Foxhound built your morning queue. Found 12 jobs matching your profile
        and 4 strong matches worth acting on.
        <div
          style={{
            marginTop: 8,
            padding: "10px 14px",
            background: "rgba(139,92,246,0.04)",
            border: "1px solid rgba(139,92,246,0.08)",
            borderRadius: 8,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: "var(--t)" }}>
              Research Engineer
            </div>
            <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
              Remote · $180–220k · best match
            </div>
          </div>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 20,
              fontWeight: 700,
              color: "var(--v)",
            }}
          >
            94%
          </div>
        </div>
        <div
          style={{
            marginTop: 10,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--t3)",
          }}
        >
          Also queued: Staff Backend Engineer 91% · Full Stack Engineer 87%
        </div>
      </>
    ),
  },
  { type: "typing", delay: 600 },
  { type: "user", delay: 500, content: "Apply to the top one" },
  { type: "typing", delay: 1000 },
  {
    type: "agent",
    delay: 800,
    content: (
      <>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--t3)",
          }}
        >
          Reviewing the application path now. I&apos;ll submit it, turn on
          tracking, and update the brief as the research comes back.
        </span>
      </>
    ),
  },
  { type: "typing", delay: 1200 },
  {
    type: "agent",
    delay: 700,
    content: (
      <>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--g)",
          }}
        >
          ✓ Submitted · receipt captured
        </div>
        <div style={{ fontSize: 12, color: "var(--t3)", marginTop: 4 }}>
          Company research started · people research started · status tracking
          enabled
        </div>
      </>
    ),
  },
  { type: "typing", delay: 800 },
  {
    type: "agent",
    delay: 600,
    content: (
      <>
        <div style={{ fontSize: 13, color: "var(--t2)" }}>
          Brief ready for Stripe:
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--vl)",
            marginTop: 6,
          }}
        >
          → Best contact found
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--vl)",
            marginTop: 2,
          }}
        >
          → Outreach draft ready
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--vl)",
            marginTop: 2,
          }}
        >
          → Follow-up scheduled for day 5
        </div>
      </>
    ),
  },
  { type: "typing", delay: 500 },
  { type: "user", delay: 400, content: "Show me the brief" },
  { type: "typing", delay: 900 },
  {
    type: "agent",
    delay: 600,
    content: (
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          color: "var(--g)",
        }}
      >
        ✓ Opening Foxhound Brief
      </div>
    ),
  },
];

export default function ChatDemo() {
  const [visibleMsgs, setVisibleMsgs] = useState<
    Array<{ type: string; content: ReactNode }>
  >([]);
  const [showTyping, setShowTyping] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const runDemo = useCallback(() => {
    let totalDelay = 0;

    MESSAGES.forEach((msg) => {
      totalDelay += msg.delay;

      if (msg.type === "typing") {
        setTimeout(() => setShowTyping(true), totalDelay);
        totalDelay += 700;
        setTimeout(() => setShowTyping(false), totalDelay);
      } else if (msg.type === "break") {
        setTimeout(() => {
          setVisibleMsgs((prev) => [
            ...prev,
            { type: "break", content: msg.content },
          ]);
        }, totalDelay);
      } else {
        setTimeout(() => {
          setVisibleMsgs((prev) => [
            ...prev,
            { type: msg.type, content: msg.content },
          ]);
          // Auto-scroll
          requestAnimationFrame(() => {
            if (containerRef.current) {
              containerRef.current.scrollTop =
                containerRef.current.scrollHeight;
            }
          });
        }, totalDelay);
      }
    });
  }, []);

  useEffect(() => {
    if (!wrapRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started.current) {
          started.current = true;
          runDemo();
        }
      },
      { threshold: 0.3 },
    );
    observer.observe(wrapRef.current);
    return () => observer.disconnect();
  }, [runDemo]);

  return (
    <div
      ref={wrapRef}
      style={{
        background: "var(--sf)",
        border: "1px solid var(--b)",
        borderRadius: 12,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      {/* Title bar */}
      <div
        style={{
          padding: "11px 16px",
          borderBottom: "1px solid var(--b)",
          display: "flex",
          alignItems: "center",
          gap: 8,
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
        FOXHOUND AGENT
        <span style={{ marginLeft: "auto", color: "var(--g)" }}>ACTIVE</span>
      </div>

      {/* Messages */}
      <div
        ref={containerRef}
        style={{
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          flex: 1,
          overflowY: "auto",
        }}
      >
        {visibleMsgs.map((msg, i) => {
          if (msg.type === "break") {
            return (
              <div
                key={i}
                style={{
                  textAlign: "center",
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--t3)",
                  padding: "8px 0",
                  letterSpacing: "0.06em",
                }}
              >
                {msg.content}
              </div>
            );
          }

          const isUser = msg.type === "user";
          return (
            <div
              key={i}
              style={{
                maxWidth: "88%",
                padding: "11px 15px",
                borderRadius: 10,
                fontSize: 13,
                lineHeight: 1.55,
                alignSelf: isUser ? "flex-end" : "flex-start",
                background: isUser
                  ? "linear-gradient(135deg, var(--v), var(--vd))"
                  : "var(--el)",
                border: isUser ? "none" : "1px solid var(--b)",
                color: isUser ? "white" : "var(--t2)",
                fontWeight: isUser ? 500 : 400,
                animation: "cursor-blink 0s", // Trigger repaint for smooth entry
                opacity: 1,
              }}
            >
              {msg.content}
            </div>
          );
        })}

        {/* Typing indicator */}
        {showTyping && (
          <div
            style={{
              display: "flex",
              gap: 4,
              padding: "11px 15px",
              alignSelf: "flex-start",
            }}
          >
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: "var(--t3)",
                  animation: `typing-dot 1.4s infinite ${i * 0.2}s`,
                }}
              />
            ))}
          </div>
        )}
      </div>

      <style jsx>{`
        @keyframes typing-dot {
          0%,
          60%,
          100% {
            opacity: 0.3;
            transform: translateY(0);
          }
          30% {
            opacity: 1;
            transform: translateY(-3px);
          }
        }
      `}</style>
    </div>
  );
}
