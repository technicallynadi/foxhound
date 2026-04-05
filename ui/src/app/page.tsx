"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import LandingNav from "@/components/landing/LandingNav";
import TypingHeadline from "@/components/landing/TypingHeadline";
import ScrollReveal from "@/components/landing/ScrollReveal";
import ChatDemo from "@/components/landing/ChatDemo";
import FormFillDemo from "@/components/landing/FormFillDemo";
import Ticker from "@/components/landing/Ticker";
import AnimatedCounter from "@/components/landing/AnimatedCounter";

export default function LandingPage() {
  const features: Array<{
    n: string;
    t: ReactNode;
    d: string;
    data?: string;
  }> = [
    {
      n: "01",
      t: (
        <>
          WORKS WHILE YOU <span style={{ color: "var(--v)" }}>SLEEP</span>
        </>
      ),
      d: "Set it up once and go about your day. Foxhound finds jobs, applies, and researches around the clock. You wake up to a briefing of everything it did.",
    },
    {
      n: "02",
      t: (
        <>
          LIVE WEB <span style={{ color: "var(--v)" }}>INTELLIGENCE</span>
        </>
      ),
      d: "Foxhound searches the live web \u2014 not just job boards. It verifies postings are real, researches companies and people, and keeps watching after you apply.",
    },
    {
      n: "03",
      t: (
        <>
          ONLY STRONG <span style={{ color: "var(--v)" }}>MATCHES</span>
        </>
      ),
      d: "Foxhound only acts on strong fits. If a role isn\u2019t right, it tells you why and what to add to your resume to get there.",
    },
    {
      n: "04",
      t: (
        <>
          PEOPLE <span style={{ color: "var(--v)" }}>RESEARCH</span>
        </>
      ),
      d: "Foxhound finds the likely hiring manager and nearby contacts, then drafts outreach so every application has a next move.",
    },
    {
      n: "05",
      t: (
        <>
          FOXHOUND <span style={{ color: "var(--v)" }}>BRIEFS</span>
        </>
      ),
      d: "Every strong application becomes a living brief: proof it was submitted, company context, who to contact, a ready-to-send message, and what to do next.",
    },
    {
      n: "06",
      t: (
        <>
          STATUS, FOLLOW-UP, <span style={{ color: "var(--v)" }}>MOMENTUM</span>
        </>
      ),
      d: "After you apply, Foxhound watches the posting, catches ghost jobs, and tells you when to follow up \u2014 so nothing falls through the cracks.",
    },
  ];

  return (
    <>
      <LandingNav />

      {/* ═══ HERO ═══ */}
      <section
        className="landing-hero"
        style={{
          minHeight: "100dvh",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          textAlign: "center",
          paddingTop: 120,
          paddingBottom: 80,
          paddingLeft: "var(--section-px)",
          paddingRight: "var(--section-px)",
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* Glows — clamped to viewport to prevent horizontal overflow */}
        <div
          style={{
            position: "absolute",
            top: "-10%",
            left: "35%",
            width: "min(900px, 100vw)",
            height: "min(900px, 100vw)",
            background:
              "radial-gradient(circle, rgba(139,92,246,0.12) 0%, rgba(99,102,241,0.04) 40%, transparent 60%)",
            pointerEvents: "none",
            animation: "glow-float 12s ease-in-out infinite alternate",
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: "10%",
            right: "5%",
            width: 500,
            height: 500,
            background:
              "radial-gradient(circle, rgba(124,58,237,0.06) 0%, transparent 55%)",
            pointerEvents: "none",
            animation: "glow-float 18s ease-in-out infinite alternate-reverse",
          }}
        />

        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--v)",
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            marginBottom: 28,
            display: "flex",
            alignItems: "center",
            gap: 10,
            position: "relative",
            zIndex: 1,
          }}
        >
          ◉ Personal career agent
        </div>

        {/* Headline */}
        <div
          style={{
            position: "relative",
            marginBottom: 24,
            maxWidth: "100%",
            overflow: "hidden",
          }}
        >
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              width: "100%",
              fontFamily: "var(--font-display)",
              fontSize: "clamp(44px, 12vw, 150px)",
              fontWeight: 700,
              letterSpacing: "-0.05em",
              lineHeight: 0.88,
              textTransform: "uppercase",
              filter: "blur(22px)",
              background: "linear-gradient(135deg, #C4B5FD, #8B5CF6)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
              pointerEvents: "none",
              userSelect: "none",
              animation: "ghost-pulse 5s ease-in-out infinite",
              textAlign: "center",
            }}
          >
            STOP APPLYING.
          </div>
          <h1
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "clamp(44px, 12vw, 150px)",
              fontWeight: 700,
              letterSpacing: "-0.05em",
              lineHeight: 0.88,
              textTransform: "uppercase",
              position: "relative",
              zIndex: 1,
            }}
          >
            STOP APPLYING.
            <br />
            <span
              className="hero-sub"
              style={{ fontSize: "clamp(28px, 8vw, 100px)" }}
            >
              START <TypingHeadline />
            </span>
          </h1>
        </div>

        <p
          style={{
            maxWidth: 520,
            fontSize: 16,
            color: "var(--t2)",
            lineHeight: 1.7,
            textAlign: "center",
            position: "relative",
            zIndex: 1,
          }}
        >
          Upload your resume once. Foxhound takes it from there — finding jobs,
          applying to the best ones, researching every company, and following up
          at the right time. Go about your day. We&apos;ll reach out when something
          needs you.
        </p>

        <ScrollReveal delay={2}>
          <div className="hero-stats">
            {[
              { value: 100, suffix: "+", label: "Companies" },
              { value: 10000, suffix: "+", label: "Jobs indexed" },
              { value: 60, suffix: "s", label: "Per application" },
              { value: 70, suffix: "%", label: "Match floor" },
            ].map((stat) => (
              <div key={stat.label} className="hero-stat">
                <AnimatedCounter target={stat.value} suffix={stat.suffix} />
                <div className="hero-stat-label">{stat.label}</div>
              </div>
            ))}
          </div>
        </ScrollReveal>

        <ScrollReveal delay={3}>
          <div
            style={{
              display: "flex",
              gap: 12,
              marginTop: 40,
              flexWrap: "wrap",
              justifyContent: "center",
            }}
          >
            <Link href="/login" className="btn-solid">
              Join Early Access →
            </Link>
            <Link href="/jobs" className="btn-ghost">
              Browse Jobs
            </Link>
          </div>
        </ScrollReveal>

        <div
          className="hero-badge"
          style={{
            marginTop: 40,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--t3)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          V.01 / Early Access
        </div>
      </section>

      <section className="trust-bar">
        <div className="trust-label">Trusted by candidates targeting roles at</div>
        <div className="trust-logos">
          <span>Anthropic</span>
          <span>Vercel</span>
          <span>Figma</span>
          <span>Ramp</span>
          <span>Datadog</span>
        </div>
      </section>

      <Ticker />

      {/* Agent demo */}
      <section
        id="how"
        style={{
          padding: "40px var(--section-px) 40px",
          maxWidth: 1200,
          margin: "0 auto",
          position: "relative",
          zIndex: 1,
        }}
      >
        <ScrollReveal>
          <div className="section-label">01 / How it works</div>
        </ScrollReveal>
        <ScrollReveal delay={1}>
          <div className="section-heading">
            YOUR AGENT <span className="dim">IN ACTION</span>
          </div>
        </ScrollReveal>
        <ScrollReveal delay={2}>
          <p
            style={{
              fontSize: 16,
              color: "var(--t2)",
              lineHeight: 1.7,
              maxWidth: 520,
              marginTop: 14,
            }}
          >
            Set up your profile once and walk away. Foxhound runs your entire
            job search in the background — finding roles, applying, researching
            companies, and reaching out when something needs your attention.
            Check in when you want, or don&apos;t. Either way, it&apos;s working.
          </p>
        </ScrollReveal>

        <div
          className="demo-grid"
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 32,
            marginTop: 56,
            alignItems: "stretch",
          }}
        >
          <ScrollReveal delay={3}>
            <ChatDemo />
          </ScrollReveal>
          <ScrollReveal delay={4}>
            <FormFillDemo />
          </ScrollReveal>
        </div>

        <ScrollReveal delay={4}>
          <div className="inline-cta">
            <p>Upload your resume once. Let Foxhound run the rest.</p>
            <Link href="/login" className="btn-solid">
              Start Free →
            </Link>
          </div>
        </ScrollReveal>
      </section>

      <div className="divider" />

      {/* Features */}
      <section
        id="features"
        style={{
          paddingTop: 32,
          paddingBottom: 0,
          paddingLeft: "var(--section-px)",
          paddingRight: "var(--section-px)",
          maxWidth: 1200,
          margin: "0 auto",
          position: "relative",
          zIndex: 1,
        }}
      >
        <ScrollReveal>
          <div className="section-label">02 / Why Foxhound</div>
        </ScrollReveal>
        <ScrollReveal delay={1}>
          <div className="section-heading">
            NOT ANOTHER <span className="dim">AUTO-APPLY BOT.</span>
          </div>
        </ScrollReveal>

        {features.map((f) => (
          <ScrollReveal key={f.n}>
            <div
              style={{ padding: "64px 0", borderBottom: "1px solid var(--b)" }}
            >
              <div
                className="feature-row"
                style={{
                  display: "grid",
                  gridTemplateColumns: "48px 1fr",
                  gap: 24,
                }}
              >
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "var(--t3)",
                    paddingTop: 6,
                  }}
                >
                  {f.n}
                </div>
                <div>
                  <div
                    style={{
                      fontFamily: "var(--font-display)",
                      fontSize: "clamp(24px, 4.5vw, 56px)",
                      fontWeight: 700,
                      letterSpacing: "-0.04em",
                      lineHeight: 1,
                      textTransform: "uppercase",
                    }}
                  >
                    {f.t}
                  </div>
                  <p
                    style={{
                      fontSize: 14,
                      color: "var(--t2)",
                      lineHeight: 1.7,
                      maxWidth: 440,
                      marginTop: 12,
                    }}
                  >
                    {f.d}
                  </p>
                  {f.data && (
                    <div
                      style={{
                        marginTop: 16,
                        fontFamily: "var(--font-mono)",
                        fontSize: 13,
                        color: "var(--vl)",
                        padding: "8px 16px",
                        background: "var(--vf)",
                        border: "1px solid rgba(139,92,246,0.08)",
                        borderRadius: 6,
                        display: "inline-block",
                      }}
                    >
                      {f.data}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </ScrollReveal>
        ))}
      </section>

      <div className="divider" />

      {/* ═══ REMOTE CONTROL ═══ */}
      <section
        className="notif-section"
        style={{
          padding: "80px var(--section-px) 80px",
          maxWidth: 1200,
          margin: "0 auto",
          position: "relative",
          zIndex: 1,
        }}
      >
        <ScrollReveal>
          <div className="section-label">03 / Foxhound Anywhere</div>
        </ScrollReveal>
        <ScrollReveal delay={1}>
          <div className="section-heading">
            STAY IN THE LOOP.{" "}
            <span className="dim">STEER IT FROM ANYWHERE.</span>
          </div>
        </ScrollReveal>
        <ScrollReveal delay={2}>
          <p
            style={{
              fontSize: 16,
              color: "var(--t2)",
              lineHeight: 1.7,
              maxWidth: 520,
              marginTop: 14,
            }}
          >
            Foxhound keeps working in the background and reaches you when
            something matters. Get updates, approve actions, answer questions,
            or steer the agent from Slack, Discord, or email without living in
            the dashboard.
          </p>
        </ScrollReveal>

        {/* Channel pills */}
        <ScrollReveal delay={2}>
          <div
            className="notif-channels"
            style={{
              display: "flex",
              gap: 10,
              marginTop: 28,
              flexWrap: "wrap",
            }}
          >
            {[
              {
                label: "Slack",
                icon: (
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313z"
                      fill="currentColor"
                    />
                    <path
                      d="M8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312z"
                      fill="currentColor"
                    />
                    <path
                      d="M18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zm-1.27 0a2.528 2.528 0 0 1-2.522 2.521 2.528 2.528 0 0 1-2.52-2.521V2.522A2.528 2.528 0 0 1 15.165 0a2.528 2.528 0 0 1 2.521 2.522v6.312z"
                      fill="currentColor"
                    />
                    <path
                      d="M15.165 18.956a2.528 2.528 0 0 1 2.521 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zm0-1.27a2.527 2.527 0 0 1-2.52-2.522 2.527 2.527 0 0 1 2.52-2.52h6.313A2.528 2.528 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.521h-6.313z"
                      fill="currentColor"
                    />
                  </svg>
                ),
              },
              {
                label: "Discord",
                icon: (
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.086-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.332-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.086-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.332-.946 2.418-2.157 2.418z"
                      fill="currentColor"
                    />
                  </svg>
                ),
              },
              {
                label: "Email",
                icon: (
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <rect x="2" y="4" width="20" height="16" rx="2" />
                    <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
                  </svg>
                ),
              },
            ].map((ch) => (
              <div
                key={ch.label}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "6px 14px",
                  background: "var(--vf)",
                  border: "1px solid rgba(139,92,246,0.08)",
                  borderRadius: 6,
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: "var(--vl)",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                }}
              >
                {ch.icon}
                {ch.label}
              </div>
            ))}
          </div>
        </ScrollReveal>

        {/* Notifications + remote control */}
        <ScrollReveal delay={3}>
          <div
            className="notif-card-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "1.1fr 0.9fr",
              gap: 24,
              marginTop: 48,
            }}
          >
            <div
              style={{
                display: "grid",
                gap: 16,
              }}
            >
              {/* Card 1: Application Submitted */}
              <div
                className="notif-card"
                style={{
                  background: "var(--sf)",
                  border: "1px solid var(--b)",
                  borderRadius: 12,
                  padding: 0,
                  overflow: "hidden",
                  position: "relative",
                }}
              >
                <div style={{ padding: "20px 20px 22px" }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: 16,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                      }}
                    >
                      <div
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: 6,
                          background: "var(--el)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontFamily: "var(--font-display)",
                          fontSize: 11,
                          fontWeight: 700,
                          color: "var(--v)",
                        }}
                      >
                        F
                      </div>
                      <span
                        style={{
                          fontFamily: "var(--font-display)",
                          fontSize: 13,
                          fontWeight: 600,
                          color: "var(--t)",
                        }}
                      >
                        Foxhound
                      </span>
                    </div>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--t3)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      2m ago
                    </span>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 8,
                    }}
                  >
                    <span
                      className="status-dot status-dot-green"
                      aria-hidden="true"
                    />
                    <span
                      style={{
                        fontFamily: "var(--font-display)",
                        fontSize: 14,
                        fontWeight: 600,
                        color: "var(--t)",
                      }}
                    >
                      Application Submitted
                    </span>
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-body)",
                      fontSize: 13,
                      color: "var(--t2)",
                      lineHeight: 1.6,
                      marginBottom: 14,
                    }}
                  >
                    <strong style={{ color: "var(--t)" }}>Acme Corp</strong>{" "}
                    &mdash; Senior Software Engineer
                  </div>

                  <div
                    style={{
                      display: "flex",
                      gap: 12,
                      flexWrap: "wrap",
                      paddingTop: 12,
                      borderTop: "1px solid var(--b)",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--vl)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      SUBMITTED
                    </span>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--g)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      RESUME UPLOADED
                    </span>
                  </div>
                </div>
              </div>

              {/* Card 2: Question Needs Answer */}
              <div
                className="notif-card"
                style={{
                  background: "var(--sf)",
                  border: "1px solid var(--b)",
                  borderRadius: 12,
                  padding: 0,
                  overflow: "hidden",
                  position: "relative",
                }}
              >
                <div style={{ padding: "20px 20px 22px" }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: 16,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                      }}
                    >
                      <div
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: 6,
                          background: "var(--el)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontFamily: "var(--font-display)",
                          fontSize: 11,
                          fontWeight: 700,
                          color: "var(--v)",
                        }}
                      >
                        F
                      </div>
                      <span
                        style={{
                          fontFamily: "var(--font-display)",
                          fontSize: 13,
                          fontWeight: 600,
                          color: "var(--t)",
                        }}
                      >
                        Foxhound
                      </span>
                    </div>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--t3)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      18m ago
                    </span>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 8,
                    }}
                  >
                    <span
                      className="status-dot status-dot-violet"
                      aria-hidden="true"
                    />
                    <span
                      style={{
                        fontFamily: "var(--font-display)",
                        fontSize: 14,
                        fontWeight: 600,
                        color: "var(--t)",
                      }}
                    >
                      Question Needs Answer
                    </span>
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-body)",
                      fontSize: 13,
                      color: "var(--t2)",
                      lineHeight: 1.6,
                      marginBottom: 14,
                    }}
                  >
                    <strong style={{ color: "var(--t)" }}>Nova Labs</strong>{" "}
                    &mdash; Staff Frontend Engineer
                  </div>

                  <div
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      color: "var(--t2)",
                      background: "var(--bg)",
                      border: "1px solid var(--b)",
                      borderRadius: 6,
                      padding: "10px 12px",
                      lineHeight: 1.5,
                    }}
                  >
                    <span style={{ color: "var(--t3)" }}>&ldquo;</span>
                    Describe a time you improved developer experience at scale.
                    <span style={{ color: "var(--t3)" }}>&rdquo;</span>
                  </div>
                </div>
              </div>

              {/* Card 3: Status Change */}
              <div
                className="notif-card"
                style={{
                  background: "var(--sf)",
                  border: "1px solid var(--b)",
                  borderRadius: 12,
                  padding: 0,
                  overflow: "hidden",
                  position: "relative",
                }}
              >
                <div style={{ padding: "20px 20px 22px" }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: 16,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                      }}
                    >
                      <div
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: 6,
                          background: "var(--el)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontFamily: "var(--font-display)",
                          fontSize: 11,
                          fontWeight: 700,
                          color: "var(--v)",
                        }}
                      >
                        F
                      </div>
                      <span
                        style={{
                          fontFamily: "var(--font-display)",
                          fontSize: 13,
                          fontWeight: 600,
                          color: "var(--t)",
                        }}
                      >
                        Foxhound
                      </span>
                    </div>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--t3)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      1h ago
                    </span>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 8,
                    }}
                  >
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: "#FBBF24",
                        boxShadow: "0 0 6px #FBBF24",
                        display: "inline-block",
                        flexShrink: 0,
                      }}
                      aria-hidden="true"
                    />
                    <span
                      style={{
                        fontFamily: "var(--font-display)",
                        fontSize: 14,
                        fontWeight: 600,
                        color: "var(--t)",
                      }}
                    >
                      Posting Closed
                    </span>
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-body)",
                      fontSize: 13,
                      color: "var(--t2)",
                      lineHeight: 1.6,
                      marginBottom: 14,
                    }}
                  >
                    <strong style={{ color: "var(--t)" }}>Apex Inc</strong>{" "}
                    &mdash; Design Engineer
                  </div>

                  <div
                    style={{
                      display: "flex",
                      gap: 12,
                      flexWrap: "wrap",
                      paddingTop: 12,
                      borderTop: "1px solid var(--b)",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--t3)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      APPLIED 3 DAYS AGO
                    </span>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--warning)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      NO LONGER ACCEPTING
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                maxWidth: 560,
              }}
            >
              {/* User message */}
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div
                  style={{
                    background: "var(--v)",
                    color: "#fff",
                    padding: "10px 16px",
                    borderRadius: "14px 14px 4px 14px",
                    fontFamily: "var(--font-body)",
                    fontSize: 14,
                    lineHeight: 1.5,
                    maxWidth: "75%",
                  }}
                >
                  Apply to my top match
                </div>
              </div>

              {/* Bot response */}
              <div
                style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background: "var(--el)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--font-display)",
                    fontSize: 11,
                    fontWeight: 700,
                    color: "var(--v)",
                    flexShrink: 0,
                  }}
                >
                  F
                </div>
                <div
                  style={{
                    background: "var(--sf)",
                    border: "1px solid var(--b)",
                    padding: "12px 16px",
                    borderRadius: "4px 14px 14px 14px",
                    fontFamily: "var(--font-body)",
                    fontSize: 14,
                    color: "var(--t2)",
                    lineHeight: 1.6,
                    maxWidth: "80%",
                  }}
                >
                  Applying to{" "}
                  <strong style={{ color: "var(--t)" }}>Acme</strong> &mdash;
                  Senior Software Engineer (87% match). I&apos;ll let you know
                  when it&apos;s done.
                </div>
              </div>

              {/* Bot follow-up with card */}
              <div
                style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background: "transparent",
                    flexShrink: 0,
                  }}
                />
                <div
                  style={{
                    background: "var(--sf)",
                    border: "1px solid var(--b)",
                    borderRadius: "4px 14px 14px 14px",
                    padding: "14px 16px",
                    maxWidth: "80%",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 10,
                    }}
                  >
                    <span
                      className="status-dot status-dot-green"
                      aria-hidden="true"
                    />
                    <span
                      style={{
                        fontFamily: "var(--font-display)",
                        fontSize: 13,
                        fontWeight: 600,
                        color: "var(--t)",
                      }}
                    >
                      Application Submitted
                    </span>
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-body)",
                      fontSize: 13,
                      color: "var(--t2)",
                      lineHeight: 1.6,
                      marginBottom: 10,
                    }}
                  >
                    Application submitted. Resume uploaded. I need your input on{" "}
                    <strong style={{ color: "var(--t)" }}>2 questions</strong>:
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      color: "var(--t2)",
                      background: "var(--bg)",
                      border: "1px solid var(--b)",
                      borderRadius: 6,
                      padding: "10px 12px",
                      lineHeight: 1.7,
                    }}
                  >
                    1. Why are you interested in Acme?
                    <br />
                    2. Salary expectations?
                    <br />
                    <br />
                    <span style={{ color: "var(--t3)" }}>
                      Reply with your answers: 1. [answer] 2. [answer]
                    </span>
                  </div>
                </div>
              </div>

              {/* User reply */}
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div
                  style={{
                    background: "var(--v)",
                    color: "#fff",
                    padding: "10px 16px",
                    borderRadius: "14px 14px 4px 14px",
                    fontFamily: "var(--font-body)",
                    fontSize: 14,
                    lineHeight: 1.5,
                    maxWidth: "75%",
                  }}
                >
                  1. Love Acme&apos;s developer tools &nbsp;2. $180k base
                </div>
              </div>

              {/* Bot confirmation */}
              <div
                style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background: "var(--el)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--font-display)",
                    fontSize: 11,
                    fontWeight: 700,
                    color: "var(--v)",
                    flexShrink: 0,
                  }}
                >
                  F
                </div>
                <div
                  style={{
                    background: "var(--sf)",
                    border: "1px solid var(--b)",
                    padding: "12px 16px",
                    borderRadius: "4px 14px 14px 14px",
                    fontFamily: "var(--font-body)",
                    fontSize: 14,
                    color: "var(--t2)",
                    lineHeight: 1.6,
                  }}
                >
                  Got it. Answers submitted. Application complete.
                </div>
              </div>
            </div>
          </div>
        </ScrollReveal>
      </section>

      <div className="divider" />

      {/* Jobs preview */}
      <section
        style={{
          padding: "60px var(--section-px) 40px",
          maxWidth: 1200,
          margin: "0 auto",
          position: "relative",
          zIndex: 1,
        }}
      >
        <ScrollReveal>
          <div style={{ padding: "12px" }} className="section-label">
            05 / Opportunity Flow
          </div>
        </ScrollReveal>
        <ScrollReveal delay={1}>
          <div className="section-heading">
            SEE WHAT FOXHOUND FOUND.{" "}
            <span className="dim">ACT ONLY WHEN YOU WANT TO.</span>
          </div>
        </ScrollReveal>
        <ScrollReveal delay={2}>
          <p style={{ color: "var(--t2)", marginTop: 12, fontSize: 15 }}>
            Foxhound surfaces strong matches and explains weak ones. Review them
            yourself or let Foxhound handle everything in the background.
          </p>
        </ScrollReveal>

        <ScrollReveal delay={3}>
          <div
            className="landing-jobs-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 2,
              marginTop: 48,
              background: "var(--b)",
              border: "1px solid var(--b)",
            }}
          >
            {[
              {
                s: "Remote",
                t: "Senior ML Engineer",
                c: "AI Research Co.",
                i: "94% match · ready to apply",
              },
              {
                s: "San Francisco",
                t: "Staff Backend Engineer",
                c: "Payments Co.",
                i: "91% match · high-priority fit",
              },
              {
                s: "Remote",
                t: "Product Designer",
                c: "Dev Tools Co.",
                i: "87% match · review and queue",
              },
            ].map((j) => (
              <div
                key={j.t}
                style={{
                  background: "var(--bg)",
                  padding: 26,
                  position: "relative",
                }}
              >
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    color: "var(--t3)",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    marginBottom: 10,
                  }}
                >
                  {j.s}
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: 17,
                    fontWeight: 600,
                  }}
                >
                  {j.t}
                </div>
                <div style={{ fontSize: 13, color: "var(--t2)", marginTop: 2 }}>
                  {j.c}
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--vl)",
                    marginTop: 14,
                    paddingTop: 14,
                    borderTop: "1px solid var(--b)",
                  }}
                >
                  {j.i}
                </div>
                <Link
                  href="/login"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--t3)",
                    marginTop: 10,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                  }}
                >
                  See match % ↗
                </Link>
              </div>
            ))}
          </div>
        </ScrollReveal>
      </section>

      {/* Security */}
      <ScrollReveal>
        <div
          style={{
            textAlign: "center",
            padding: "32px 24px",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--t3)",
            letterSpacing: "0.04em",
            borderTop: "1px solid var(--b)",
          }}
        >
          <span aria-hidden="true">🔒</span> Your data is encrypted. Foxhound
          follows your autonomy settings for every application. Confirmation
          receipt for every submission.
        </div>
      </ScrollReveal>

      {/* Bottom CTA */}
      <section
        style={{
          textAlign: "center",
          padding: "24px var(--section-px) var(--section-py)",
          position: "relative",
          zIndex: 1,
        }}
      >
        <div
          style={{
            position: "absolute",
            top: "15%",
            left: "50%",
            transform: "translateX(-50%)",
            width: 700,
            height: 500,
            background:
              "radial-gradient(ellipse, rgba(139,92,246,0.07) 0%, transparent 50%)",
            pointerEvents: "none",
          }}
        />
        <ScrollReveal>
          <div style={{ padding: "12px" }} className="section-label">
            Ready?
          </div>
        </ScrollReveal>
        <ScrollReveal delay={1}>
          <h2
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "clamp(32px, 7vw, 80px)",
              fontWeight: 700,
              letterSpacing: "-0.05em",
              lineHeight: 0.88,
              textTransform: "uppercase",
            }}
          >
            STOP APPLYING.
            <br />
            <span
              style={{
                fontSize: "clamp(24px, 5vw, 56px)",
                color: "var(--v)",
                fontFamily: "var(--font-mono)",
                letterSpacing: "-0.02em",
              }}
            >
              START WAKING UP TO PROGRESS.
            </span>
          </h2>
        </ScrollReveal>
        <ScrollReveal delay={2}>
          <div
            style={{
              display: "flex",
              gap: 12,
              justifyContent: "center",
              flexWrap: "wrap",
              marginTop: 40,
            }}
          >
            <Link href="/login" className="btn-solid">
              Join Early Access →
            </Link>
            <Link href="/jobs" className="btn-ghost">
              Browse Jobs
            </Link>
          </div>
        </ScrollReveal>
      </section>

      <section className="founder-note">
        <p className="founder-quote">
          &ldquo;Foxhound exists for people tired of submitting great applications
          into silence. You should always know what happened and what to do
          next.&rdquo;
        </p>
        <p className="founder-attribution">Founding Team / Foxhound</p>
      </section>
    </>
  );
}
