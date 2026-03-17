"use client";

export interface TerminalLine {
  text: string;
  color?: "purple" | "green" | "muted" | "primary" | "secondary" | "glass";
}

interface GlassTerminalProps {
  title?: string;
  lines: TerminalLine[];
  showCursor?: boolean;
  className?: string;
}

const COLOR_MAP: Record<string, string> = {
  purple: "text-accent-purple",
  green: "text-accent-green",
  muted: "text-text-muted",
  primary: "text-text-primary",
  secondary: "text-text-secondary",
  glass: "text-[rgba(255,255,255,0.13)]",
};

export default function GlassTerminal({
  title = "",
  lines,
  showCursor = true,
  className = "",
}: GlassTerminalProps) {
  return (
    <div
      className={`rounded-xl overflow-hidden border border-glass-border-strong ${className}`}
      style={{
        background: "linear-gradient(180deg, rgba(255,255,255,0.02) 0%, rgba(10,10,26,1) 100%)",
        boxShadow: "0 8px 60px rgba(139,92,246,0.08)",
      }}
    >
      <div className="flex items-center justify-between px-4 py-2.5 bg-[rgba(255,255,255,0.03)] border-b border-glass-border">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-[#EF4444]" />
          <div className="w-3 h-3 rounded-full bg-[#F59E0B]" />
          <div className="w-3 h-3 rounded-full bg-[#22C55E]" />
        </div>
        {title && (
          <span className="font-mono text-xs text-text-muted">{title}</span>
        )}
        <div className="w-16" />
      </div>

      <div className="px-5 py-4 space-y-1 font-mono text-[13px] leading-relaxed">
        {lines.map((line, i) => (
          <div key={i} className={COLOR_MAP[line.color ?? "secondary"]}>
            {line.text || "\u00A0"}
          </div>
        ))}
        {showCursor && (
          <div className="flex items-center">
            <span className="w-2 h-4 bg-accent-purple rounded-sm animate-blink" />
          </div>
        )}
      </div>
    </div>
  );
}
