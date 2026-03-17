"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ScanSearch, Eye, EyeOff, Github, Mail } from "lucide-react";
import Link from "next/link";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    router.push("/dashboard");
  }

  return (
    <div className="relative flex items-center justify-center min-h-screen px-6 bg-bg-primary overflow-hidden">
      <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-[#8B5CF6]/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/4 pointer-events-none" />

      <div className="animate-fade-in-up relative w-full max-w-md">
        <div className="bg-[rgba(255,255,255,0.04)] backdrop-blur-xl border border-[rgba(255,255,255,0.08)] rounded-2xl p-10">
          <div className="flex items-center justify-center mb-6">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-[#8B5CF6]/20 to-[#7C3AED]/10 border border-[#8B5CF6]/20">
              <ScanSearch className="w-5 h-5 text-accent-purple" />
            </div>
          </div>

          <h1 className="text-2xl font-bold text-center mb-1">Sign In</h1>
          <p className="text-sm text-text-muted text-center mb-8">
            Keep it all together and you&apos;ll be fine.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="block text-sm text-text-secondary mb-1.5"
              >
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full px-4 py-3 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg text-text-primary placeholder:text-text-muted text-sm focus:outline-none focus:border-[#8B5CF6]/40 transition-colors"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label
                  htmlFor="password"
                  className="text-sm text-text-secondary"
                >
                  Password
                </label>
                <button
                  type="button"
                  className="text-xs text-accent-purple hover:underline"
                >
                  Forgot Password?
                </button>
              </div>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  className="w-full px-4 py-3 pr-10 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg text-text-primary placeholder:text-text-muted text-sm focus:outline-none focus:border-[#8B5CF6]/40 transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary transition-colors"
                >
                  {showPassword ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="w-full py-3 bg-gradient-to-r from-[#8B5CF6] to-[#7C3AED] text-white font-semibold text-sm rounded-lg hover:opacity-90 transition-opacity"
            >
              Sign In
            </button>
          </form>

          <div className="flex items-center gap-3 my-6">
            <div className="flex-1 h-px bg-[rgba(255,255,255,0.08)]" />
            <span className="text-xs text-text-muted">or</span>
            <div className="flex-1 h-px bg-[rgba(255,255,255,0.08)]" />
          </div>

          <div className="space-y-3">
            <button className="w-full flex items-center justify-center gap-2 py-3 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg text-sm text-text-secondary hover:border-[rgba(255,255,255,0.15)] hover:text-text-primary transition-colors">
              <Github className="w-4 h-4" />
              Sign in with GitHub
            </button>
            <button className="w-full flex items-center justify-center gap-2 py-3 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg text-sm text-text-secondary hover:border-[rgba(255,255,255,0.15)] hover:text-text-primary transition-colors">
              <Mail className="w-4 h-4" />
              Sign in with Google
            </button>
          </div>

          <p className="text-sm text-text-muted text-center mt-6">
            New to Foxhound?{" "}
            <Link
              href="/auth/signup"
              className="text-accent-purple hover:underline"
            >
              Sign Up
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
