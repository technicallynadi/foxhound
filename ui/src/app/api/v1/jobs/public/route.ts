import { NextResponse } from "next/server";

// Public jobs feed served directly from the frontend — no backend or database
// required. Pulls live remote listings from Remotive's free public API and maps
// them into the shape the jobs page expects. This is the fallback that keeps the
// public site populated when the Python backend / database isn't connected.

export const revalidate = 1800; // cache upstream for 30 minutes

const REMOTIVE_URL = "https://remotive.com/api/remote-jobs";
const UPSTREAM_LIMIT = 200; // enough for a few pages of infinite scroll

interface RemotiveJob {
  id: number;
  url: string;
  title: string;
  company_name: string;
  category?: string;
  candidate_required_location?: string;
  publication_date?: string;
}

function mapJob(r: RemotiveJob) {
  return {
    id: String(r.id),
    title: r.title,
    company: r.company_name,
    location: r.candidate_required_location?.trim() || "Remote",
    remote_type: "remote",
    ats_type: null,
    source: "remotive",
    apply_url: r.url,
    salary_min: null,
    salary_max: null,
    posted_at: r.publication_date || null,
  };
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const page = Math.max(1, parseInt(searchParams.get("page") || "1", 10) || 1);
  const perPage = Math.min(
    50,
    Math.max(1, parseInt(searchParams.get("per_page") || "50", 10) || 50),
  );
  const search = (searchParams.get("search") || "").slice(0, 100);

  const upstream = new URL(REMOTIVE_URL);
  upstream.searchParams.set("limit", String(UPSTREAM_LIMIT));
  if (search) upstream.searchParams.set("search", search);

  try {
    const res = await fetch(upstream.toString(), {
      headers: { "User-Agent": "foxhound-web" },
      next: { revalidate },
    });
    if (!res.ok) throw new Error(`remotive responded ${res.status}`);

    const data = (await res.json()) as { jobs?: RemotiveJob[] };
    const all = Array.isArray(data.jobs) ? data.jobs : [];
    const jobs = all.slice((page - 1) * perPage, page * perPage).map(mapJob);

    return NextResponse.json({
      jobs,
      total: all.length,
      page,
      per_page: perPage,
    });
  } catch {
    // Never break the page — return an empty feed on any upstream failure.
    return NextResponse.json({ jobs: [], total: 0, page, per_page: perPage });
  }
}
