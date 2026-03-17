interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-lg bg-[rgba(255,255,255,0.06)] ${className}`}
    />
  );
}

export function SkeletonCard({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`bg-glass-fill border border-glass-border rounded-xl p-5 space-y-3 ${className}`}
    >
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-1/2" />
    </div>
  );
}

export function SkeletonTopBar() {
  return (
    <header className="sticky top-0 z-50 flex items-center justify-between px-7 py-3 bg-glass-fill backdrop-blur-xl border-b border-glass-border">
      <div className="flex items-center gap-3">
        <Skeleton className="w-[22px] h-[22px] rounded" />
        <Skeleton className="w-24 h-5" />
      </div>
      <div className="flex items-center gap-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="w-20 h-8 rounded-lg" />
        ))}
      </div>
      <div className="flex items-center gap-3.5">
        <Skeleton className="w-9 h-9 rounded-full" />
        <Skeleton className="w-8 h-8 rounded-full" />
      </div>
    </header>
  );
}
