import { Skeleton, SkeletonTopBar } from "@/components/ui/skeleton";

export default function SettingsLoading() {
  return (
    <div className="min-h-screen">
      <SkeletonTopBar />

      <div className="flex min-h-[calc(100vh-52px)]">
        {/* Sidebar */}
        <aside className="w-60 shrink-0 glass-panel border-r border-glass-border p-5">
          <Skeleton className="h-3 w-28 mb-4" />
          <div className="space-y-1">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full rounded-lg" />
            ))}
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 p-8 max-w-4xl space-y-7">
          <div>
            <Skeleton className="h-7 w-36 mb-2" />
            <Skeleton className="h-4 w-72" />
          </div>
          <div className="bg-glass-fill border border-glass-border rounded-xl p-6 space-y-4">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-12 w-full rounded-lg" />
            <div className="h-px bg-glass-border" />
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-10 flex-1 rounded-lg" />
              </div>
            ))}
          </div>
          <div className="bg-glass-fill border border-glass-border rounded-xl p-6 space-y-4">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-12 w-full rounded-lg" />
          </div>
        </main>
      </div>
    </div>
  );
}
