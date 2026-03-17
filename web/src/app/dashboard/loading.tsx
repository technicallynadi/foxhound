import { Skeleton, SkeletonCard, SkeletonTopBar } from "@/components/ui/skeleton";

export default function DashboardLoading() {
  return (
    <div className="flex flex-col h-screen">
      <SkeletonTopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar */}
        <aside className="w-64 shrink-0 glass-panel border-r border-glass-border p-5">
          <Skeleton className="h-3 w-24 mb-4" />
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full rounded-lg" />
            ))}
          </div>
        </aside>

        {/* Work Items Column */}
        <section className="w-[340px] shrink-0 border-r border-glass-border p-5">
          <div className="flex items-center justify-between mb-4">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-14" />
          </div>
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
          <div className="mt-6">
            <Skeleton className="h-3 w-28 mb-3" />
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-3 w-full" />
              ))}
            </div>
          </div>
        </section>

        {/* Scout Inbox Column */}
        <section className="flex-1 border-r border-glass-border p-5">
          <div className="flex items-center justify-between mb-4">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-16" />
          </div>
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        </section>

        {/* Right Column */}
        <aside className="w-96 shrink-0 p-5 space-y-4">
          <SkeletonCard />
          <div className="bg-glass-fill border border-glass-border rounded-xl p-5 space-y-3">
            <Skeleton className="h-3 w-20 mb-3" />
            <div className="grid grid-cols-3 gap-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="text-center space-y-1">
                  <Skeleton className="h-8 w-12 mx-auto" />
                  <Skeleton className="h-3 w-16 mx-auto" />
                </div>
              ))}
            </div>
            <Skeleton className="h-10 w-full rounded-lg" />
          </div>
          <div className="bg-glass-fill border border-glass-border rounded-xl flex-1">
            <div className="px-4 py-3 border-b border-glass-border">
              <Skeleton className="h-4 w-36" />
            </div>
            <div className="p-4 space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-start gap-2">
                  <Skeleton className="w-6 h-6 rounded-full shrink-0" />
                  <Skeleton className="h-12 flex-1 rounded-lg" />
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
