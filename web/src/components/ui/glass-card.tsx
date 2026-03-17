interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  padding?: string;
  hover?: boolean;
  onClick?: () => void;
}

export default function GlassCard({
  children,
  className = "",
  padding = "p-5",
  hover = false,
  onClick,
}: GlassCardProps) {
  const baseClasses = `glass-panel backdrop-blur-xl border border-glass-border rounded-xl ${padding} ${className}`;

  if (hover) {
    return (
      <div
        className={`${baseClasses} cursor-pointer transition-transform duration-200 hover:scale-[1.01]`}
        onClick={onClick}
      >
        {children}
      </div>
    );
  }

  return (
    <div className={baseClasses} onClick={onClick}>
      {children}
    </div>
  );
}
