"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ScanSearch, ArrowRight } from "lucide-react";
import Link from "next/link";

export default function LandingPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    const topics = query
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean)
      .join(",");
    router.push(`/scout?topics=${encodeURIComponent(topics)}`);
  }

  return (
    <div className="relative flex flex-col min-h-screen overflow-hidden">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-accent-purple/5 rounded-full blur-3xl" />
      </div>

      <nav className="relative z-10 flex items-center justify-end gap-3 px-6 py-4">
        <Link
          href="/auth/signin"
          className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
        >
          Log in
        </Link>
        <Link
          href="/auth/signin"
          className="px-4 py-2 text-sm font-medium text-text-primary border border-[rgba(255,255,255,0.08)] rounded-lg hover:border-text-muted transition-colors"
        >
          Sign up for free
        </Link>
      </nav>

      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 pb-20">
        <div className="animate-fade-in-up flex flex-col items-center max-w-2xl text-center">
          <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-b from-[rgba(139,92,246,0.2)] to-[rgba(139,92,246,0.03)] border border-[rgba(255,255,255,0.12)] shadow-[0_0_20px_rgba(139,92,246,0.08),inset_0_1px_0_rgba(255,255,255,0.06)] mb-8">
            <ScanSearch className="w-8 h-8 text-accent-purple" />
          </div>

          <h1 className="text-4xl sm:text-5xl font-extrabold leading-tight mb-4 tracking-tight">
            Scout ideas worth building.
            <br />
            Turn them into real systems.
          </h1>

          <p className="text-lg text-text-secondary mb-10 max-w-lg">
            Foxhound scans real-world signals and turns them into apps, tools,
            and agent-ready systems — in minutes.
          </p>

          <form
            onSubmit={handleSubmit}
            className="relative w-full max-w-xl mb-4"
          >
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Describe a space, problem, or idea..."
              className="w-full px-6 py-4 pr-40 rounded-full bg-gradient-to-b from-[rgba(255,255,255,0.06)] to-[rgba(255,255,255,0.02)] backdrop-blur-xl border border-[rgba(255,255,255,0.12)] shadow-[0_0_20px_rgba(139,92,246,0.06),inset_0_1px_0_rgba(255,255,255,0.06)] text-text-primary placeholder:text-text-muted text-base focus:outline-none focus:border-accent-purple/40 transition-colors"
            />
            <button
              type="submit"
              className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5 px-5 py-2.5 bg-gradient-to-r from-[#8B5CF6] to-[#7C3AED] text-white font-medium text-sm rounded-full hover:opacity-90 transition-opacity"
            >
              Run Scout
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
