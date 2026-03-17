import { Skeleton, SkeletonCard, SkeletonTopBar } from "@/components/ui/skeleton";

export default function BuildsLoading() {
  return (
    <div className="min-h-screen">
      <SkeletonTopBar />

      <div className="max-w-5xl mx-auto px-10 py-8">
        <div className="flex items-center justify-between mb-6">
          <Skeleton className="h-8 w-36" />
          <Skeleton className="h-4 w-28" />
        </div>

        <div className="space-y-5">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="bg-glass-fill border border-glass-border rounded-xl p-6 space-y-4"
            >
              <div className="flex items-center justify-between">
                <Skeleton className="h-6 w-2/5" />
                <Skeleton className="h-6 w-24 rounded-full" />
              </div>
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-48" />
              <div className="h-px bg-glass-border" />
              <div className="flex items-center gap-6">
                <div className="space-y-1">
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-3 w-20" />
                </div>
                <div className="space-y-1">
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-3 w-20" />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-28 rounded-lg" />
                <Skeleton className="h-10 w-36 rounded-lg" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
