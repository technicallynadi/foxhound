"use client";

import { ScanSearch, Check } from "lucide-react";

interface ScoutStatusBarProps {
  status: string;
  complete?: boolean;
}

export default function ScoutStatusBar({ status, complete = false }: ScoutStatusBarProps) {
  return (
    <div className="flex items-center gap-2 px-6 py-3 glass-panel backdrop-blur-xl border-b border-glass-border">
      {complete ? (
        <Check className="w-5 h-5 text-accent-green" />
      ) : (
        <ScanSearch className="w-5 h-5 text-accent-purple" />
      )}
      <span className="text-sm font-mono" style={{ color: complete ? "#22C55E" : "#A0A0A0" }}>
        {status}
      </span>
      {!complete && (
        <span className="w-2 h-4 bg-accent-purple/80 animate-blink ml-0.5" />
      )}
    </div>
  );
}
