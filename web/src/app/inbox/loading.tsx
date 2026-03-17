import { Skeleton, SkeletonTopBar } from "@/components/ui/skeleton";

export default function InboxLoading() {
  return (
    <div className="min-h-screen flex flex-col">
      <SkeletonTopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* Left List Pane */}
        <div className="w-[440px] shrink-0 bg-glass-fill border-r border-glass-border flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b border-glass-border">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-7 w-24 rounded-lg" />
          </div>
          <div className="flex-1">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="px-5 py-4 border-b border-glass-border space-y-2">
                <div className="flex items-center justify-between">
                  <Skeleton className="h-5 w-24 rounded" />
                  <Skeleton className="h-4 w-12" />
                </div>
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-3 w-32" />
              </div>
            ))}
          </div>
        </div>

        {/* Right Detail Pane */}
        <div className="flex-1 p-7 space-y-5">
          <div className="flex items-center justify-between">
            <Skeleton className="h-7 w-28 rounded-md" />
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-6 w-12" />
            </div>
          </div>
          <Skeleton className="h-8 w-3/4" />
          <div className="h-px bg-glass-border" />
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-20 w-full" />
          <div className="h-px bg-glass-border" />
          <Skeleton className="h-4 w-36" />
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center justify-between">
                <Skeleton className="h-3 w-32" />
                <Skeleton className="h-3 w-8" />
              </div>
            ))}
          </div>
          <div className="h-px bg-glass-border" />
          <div className="flex items-center gap-3">
            <Skeleton className="h-12 w-28 rounded-lg" />
            <Skeleton className="h-12 w-28 rounded-lg" />
          </div>
        </div>
      </div>
    </div>
  );
}
