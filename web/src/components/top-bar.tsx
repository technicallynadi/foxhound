"use client";

import { ScanSearch, Bell } from "lucide-react";
import Link from "next/link";

type TabKey = "dashboard" | "scout-inbox" | "work-items" | "builds" | "settings";

interface TopBarProps {
  activeTab?: TabKey;
}

const TABS: { key: TabKey; label: string; href: string }[] = [
  { key: "dashboard", label: "Dashboard", href: "/dashboard" },
  { key: "scout-inbox", label: "Scout Inbox", href: "/inbox" },
  { key: "work-items", label: "Work Items", href: "/work-items" },
  { key: "builds", label: "Builds", href: "/builds" },
  { key: "settings", label: "Settings", href: "/settings" },
];

export default function TopBar({ activeTab }: TopBarProps) {
  return (
    <header
      className="sticky top-0 z-50 flex items-center justify-between px-7 py-3 glass-panel backdrop-blur-xl border-b border-glass-border"
    >
      <Link href="/dashboard" className="flex items-center gap-3 shrink-0">
        <ScanSearch className="w-[22px] h-[22px] text-accent-purple" />
        <span className="text-lg font-bold text-text-primary">Foxhound</span>
        <span className="w-2 h-2 rounded-full bg-accent-green" />
      </Link>

      <nav className="flex items-center gap-2">
        {TABS.map((tab) => (
          <Link
            key={tab.key}
            href={tab.href}
            className={`px-3.5 py-1.5 rounded-lg text-[13px] transition-colors ${
              activeTab === tab.key
                ? "bg-accent-purple/[0.12] text-accent-purple font-medium"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>

      <div className="flex items-center gap-3.5 shrink-0">
        <button className="relative flex items-center justify-center w-9 h-9 rounded-full bg-[rgba(255,255,255,0.03)] transition-colors hover:bg-[rgba(255,255,255,0.06)]">
          <Bell className="w-4 h-4 text-text-secondary" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-accent-red rounded-full" />
        </button>
        <div className="w-8 h-8 rounded-full bg-[#333333]" />
      </div>
    </header>
  );
}
