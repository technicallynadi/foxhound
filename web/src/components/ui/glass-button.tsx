"use client";

interface GlassButtonProps {
  children: React.ReactNode;
  variant?: "primary" | "ghost";
  className?: string;
  onClick?: () => void;
  type?: "button" | "submit";
}

export default function GlassButton({
  children,
  variant = "primary",
  className = "",
  onClick,
  type = "button",
}: GlassButtonProps) {
  const base = "flex items-center justify-center gap-2 font-medium text-sm rounded-lg transition-opacity cursor-pointer";

  const variants = {
    primary:
      "bg-gradient-to-r from-accent-purple to-accent-purple-dim text-white px-5 py-2.5 hover:opacity-90",
    ghost:
      "border border-glass-border text-text-secondary px-4 py-2 hover:border-glass-border-strong hover:text-text-primary",
  };

  return (
    <button
      type={type}
      onClick={onClick}
      className={`${base} ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
