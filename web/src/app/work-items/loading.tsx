import { Skeleton, SkeletonTopBar } from "@/components/ui/skeleton";

export default function WorkItemsLoading() {
  return (
    <div className="min-h-screen flex flex-col">
      <SkeletonTopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* Left List Pane */}
        <div className="w-[440px] shrink-0 bg-glass-fill border-r border-glass-border flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b border-glass-border">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-7 w-28 rounded-lg" />
          </div>
          <div className="flex-1">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="px-5 py-4 border-b border-glass-border space-y-2">
                <div className="flex items-center justify-between">
                  <Skeleton className="h-5 w-20 rounded" />
                  <Skeleton className="h-4 w-12" />
                </div>
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-3 w-24" />
              </div>
            ))}
          </div>
        </div>

        {/* Right Detail Pane */}
        <div className="flex-1 p-7">
          <div className="max-w-2xl space-y-5">
            <div className="flex items-center gap-3">
              <Skeleton className="h-6 w-20 rounded" />
              <Skeleton className="h-6 w-24 rounded" />
              <Skeleton className="h-5 w-12" />
            </div>
            <Skeleton className="h-8 w-3/4" />
            <div className="h-px bg-glass-border" />
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-16 w-full" />
            <div className="h-px bg-glass-border" />
            <Skeleton className="h-3 w-36" />
            <div className="grid grid-cols-2 gap-x-8 gap-y-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center justify-between">
                  <Skeleton className="h-3 w-36" />
                  <Skeleton className="h-3 w-8" />
                </div>
              ))}
            </div>
            <div className="h-px bg-glass-border" />
            <Skeleton className="h-3 w-28" />
            <div className="grid grid-cols-2 gap-4">
              <Skeleton className="h-14 rounded-lg" />
              <Skeleton className="h-14 rounded-lg" />
            </div>
            <div className="h-px bg-glass-border" />
            <div className="flex items-center gap-3">
              <Skeleton className="h-10 w-32 rounded-lg" />
              <Skeleton className="h-4 w-28" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
