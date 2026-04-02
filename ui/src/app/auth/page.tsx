"use client";

import { useRouter } from "next/navigation";
import { Suspense, useState, useEffect } from "react";
import { supabase } from "@/lib/supabase";

function AuthForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    if (!supabase) {
      setError(
        "Auth not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.",
      );
      setLoading(false);
      return;
    }

    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (signInError) {
      setError(signInError.message);
    } else {
      router.push("/dashboard");
    }
    setLoading(false);
  }

  return (
    <div
      style={{
        background: "var(--sf)",
        border: "1px solid var(--b)",
        borderRadius: 16,
        padding: "40px 32px",
        maxWidth: 420,
        width: "100%",
      }}
    >
      <h1
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 28,
          fontWeight: 700,
          letterSpacing: "-0.02em",
          marginBottom: 8,
        }}
      >
        Sign in
      </h1>
      <p
        style={{
          fontSize: 12,
          color: "var(--t3)",
          marginBottom: 24,
          fontFamily: "var(--font-mono)",
        }}
      >
        LOCAL DEV ONLY
      </p>

      <form
        onSubmit={handleSubmit}
        style={{ display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div>
          <label
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--t3)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              display: "block",
              marginBottom: 6,
            }}
          >
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="you@example.com"
            className="input"
            style={{ width: "100%" }}
          />
        </div>
        <div>
          <label
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--t3)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              display: "block",
              marginBottom: 6,
            }}
          >
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            placeholder="Your password"
            className="input"
            style={{ width: "100%" }}
          />
        </div>

        {error && (
          <p
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--error)",
              margin: 0,
            }}
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          className="btn-solid"
          disabled={loading}
          style={{ width: "100%", justifyContent: "center", marginTop: 4 }}
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export default function AuthPage() {
  const router = useRouter();

  useEffect(() => {
    // Production: redirect to login (waitlist). Auth page is dev-only.
    if (process.env.NODE_ENV === "production") {
      router.replace("/login");
    }
  }, [router]);

  // Block render in production
  if (process.env.NODE_ENV === "production") {
    return <div style={{ minHeight: "100vh", background: "var(--bg)" }} />;
  }

  return (
    <main>
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          padding: "120px 20px 80px",
          position: "relative",
          zIndex: 1,
        }}
      >
        <Suspense
          fallback={
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--t3)",
              }}
            >
              Loading...
            </div>
          }
        >
          <AuthForm />
        </Suspense>
      </div>
    </main>
  );
}
