"use client";

import Link from "next/link";
import LandingNav from "@/components/landing/LandingNav";
import TypingHeadline from "@/components/landing/TypingHeadline";
import ScrollReveal from "@/components/landing/ScrollReveal";
import ChatDemo from "@/components/landing/ChatDemo";
import FormFillDemo from "@/components/landing/FormFillDemo";
import Ticker from "@/components/landing/Ticker";

export default function LandingPage() {
  return (
    <>
      <LandingNav />

      {/* ═══ HERO ═══ */}
      <section
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          textAlign: "center",
          padding: "var(--section-py) var(--section-px) 100px",
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* Glows */}
        <div
          style={{
            position: "absolute",
            top: "-10%",
            left: "35%",
            width: 900,
            height: 900,
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
        <div style={{ position: "relative", marginBottom: 24 }}>
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              fontFamily: "var(--font-display)",
              fontSize: "clamp(52px, 12vw, 150px)",
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
              whiteSpace: "nowrap",
            }}
          >
            STOP APPLYING.
          </div>
          <h1
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "clamp(52px, 12vw, 150px)",
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
            <span style={{ fontSize: "clamp(36px, 8vw, 100px)" }}>
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
          Your personal career agent. Upload your resume, pick a job, and
          Foxhound handles the rest.
        </p>

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
              Join Beta →
            </Link>
            <Link href="/jobs" className="btn-ghost">
              Browse Jobs
            </Link>
          </div>
        </ScrollReveal>

        <div
          style={{
            position: "absolute",
            bottom: 28,
            right: 48,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--t3)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          V.01 / Beta
        </div>
      </section>

      <Ticker />

      {/* Agent demo */}
      <section
        id="how"
        style={{
          padding: "var(--section-py) var(--section-px)",
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
            Upload your resume. Foxhound scans each form before filling — every
            field, every custom question. Fills it. Submits it. Screenshots the
            confirmation. You never touch a form.
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
      </section>

      <div className="divider" />

      {/* Features */}
      <section
        id="features"
        style={{
          paddingTop: 100,
          paddingBottom: "var(--section-py)",
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

        {[
          {
            n: "01",
            t: (
              <>
                QUALITY OVER <span style={{ color: "var(--v)" }}>VOLUME</span>
              </>
            ),
            d: "70% match floor. Your agent refuses bad matches and tells you why. 30 targeted applications beat 200 spray-and-pray.",
          },
          {
            n: "02",
            t: (
              <>
                FORM <span style={{ color: "var(--v)" }}>INTELLIGENCE</span>
              </>
            ),
            d: "Every form is scanned before filling. You see the fields, the custom questions, and how long it takes — before a single character is typed.",
            data: "12 fields · 3 custom Qs · ~8 min",
          },
          {
            n: "03",
            t: (
              <>
                FOXHOUND <span style={{ color: "var(--v)" }}>FOLLOWS UP</span>
              </>
            ),
            d: "Day 7: follow-up email to the hiring manager. Drafted, reviewed by you, sent. From applied to interviewed — your agent handles the entire lifecycle.",
          },
        ].map((f) => (
          <ScrollReveal key={f.n}>
            <div
              style={{ padding: "64px 0", borderBottom: "1px solid var(--b)" }}
            >
              <div
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

      {/* Jobs preview */}
      <section
        style={{
          padding: "var(--section-py) var(--section-px)",
          maxWidth: 1200,
          margin: "0 auto",
          position: "relative",
          zIndex: 1,
        }}
      >
        <ScrollReveal>
          <div style={{ padding: "12px" }} className="section-label">
            03 / Marketplace
          </div>
        </ScrollReveal>
        <ScrollReveal delay={1}>
          <div className="section-heading">
            BROWSE 10,000+ JOBS. <span className="dim">FREE.</span>
          </div>
        </ScrollReveal>
        <ScrollReveal delay={2}>
          <p style={{ color: "var(--t2)", marginTop: 12, fontSize: 15 }}>
            No account needed. See what companies are hiring and what their
            forms look like.
          </p>
        </ScrollReveal>

        <ScrollReveal delay={3}>
          <div
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
                s: "Ashby · Remote",
                t: "Senior ML Engineer",
                c: "AI Research Co.",
                i: "12 fields · 3 custom Qs · ~8 min",
              },
              {
                s: "Greenhouse · San Francisco",
                t: "Staff Backend Engineer",
                c: "Payments Co.",
                i: "8 fields · 2 custom Qs · ~5 min",
              },
              {
                s: "Lever · Remote",
                t: "Product Designer",
                c: "Dev Tools Co.",
                i: "10 fields · 1 custom Q · ~6 min",
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
          never applies without your approval. Screenshot proof for every
          submission. Cancel anytime.
        </div>
      </ScrollReveal>

      <div className="divider" />

      {/* Bottom CTA */}
      <section
        style={{
          textAlign: "center",
          padding: "var(--section-py) var(--section-px)",
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
              START INTERVIEWING.
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
              Join Beta →
            </Link>
            <Link href="/jobs" className="btn-ghost">
              Browse Jobs
            </Link>
          </div>
        </ScrollReveal>
        <ScrollReveal delay={3}>
          <p
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--t3)",
              marginTop: 16,
              letterSpacing: "0.03em",
            }}
          >
          </p>
        </ScrollReveal>
      </section>

      <div style={{ width: "100%", height: 1, background: "var(--b)" }} />

      {/* Footer */}
      <footer
        style={{
          padding: 48,
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gap: 20,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--t3)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          maxWidth: 1200,
          margin: "0 auto",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--t2)",
              letterSpacing: "0.1em",
              marginBottom: 4,
            }}
          >
            Product
          </div>
          <Link href="/jobs" style={{ display: "block", marginTop: 6 }}>
            Jobs
          </Link>
          <Link href="#features" style={{ display: "block", marginTop: 6 }}>
            Features
          </Link>
        </div>
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--t2)",
              letterSpacing: "0.1em",
              marginBottom: 4,
            }}
          >
            Company
          </div>
          <Link href="#" style={{ display: "block", marginTop: 6 }}>
            About
          </Link>
          <Link href="#" style={{ display: "block", marginTop: 6 }}>
            Blog
          </Link>
        </div>
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--t2)",
              letterSpacing: "0.1em",
              marginBottom: 4,
            }}
          >
            Legal
          </div>
          <Link href="#" style={{ display: "block", marginTop: 6 }}>
            Privacy
          </Link>
          <Link href="#" style={{ display: "block", marginTop: 6 }}>
            Terms
          </Link>
        </div>
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--t2)",
              letterSpacing: "0.1em",
              marginBottom: 4,
            }}
          >
            Connect
          </div>
          <Link href="#" style={{ display: "block", marginTop: 6 }}>
            Twitter/X
          </Link>
          <Link href="#" style={{ display: "block", marginTop: 6 }}>
            Discord
          </Link>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ color: "var(--t2)", marginBottom: 4 }}>Foxhound</div>
          <div>Your job search, handled.</div>
        </div>
      </footer>
    </>
  );
}
