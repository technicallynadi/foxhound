import { getAccessToken } from '@/lib/supabase';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

class ApiError extends Error {
  status: number;
  error_code?: string;
  constructor(message: string, status: number, error_code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.error_code = error_code;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;

  const token = await getAccessToken();
  const authHeaders: Record<string, string> = {};
  if (token) {
    authHeaders['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders,
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text();
    let message = `API error ${res.status}`;
    let error_code: string | undefined;
    try {
      const parsed = JSON.parse(body);
      message = parsed.detail || parsed.error || message;
      error_code = parsed.error_code;
    } catch { /* use default */ }
    throw new ApiError(message, res.status, error_code);
  }

  return res.json();
}

// ─── Dashboard ───

export async function getDashboard() {
  return request('/api/v1/dashboard');
}

export async function getDashboardActivity(page = 1, perPage = 20) {
  return request(`/api/v1/dashboard/activity?page=${page}&per_page=${perPage}`);
}

// ─── Profile ───

export async function getProfile() {
  return request<{
    id: string;
    archetype: string | null;
    target_titles: string[];
    target_locations: string[];
    remote_preference: string;
    salary_floor: number | null;
    seniority_level: string | null;
    industries: string[];
    company_size_preference: string | null;
    onboarding_step: string;
    profile_complete: boolean;
    [key: string]: unknown;
  }>('/api/v1/profile');
}

export async function updateProfile(body: { archetype?: string; [key: string]: unknown }) {
  return request('/api/v1/profile', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export async function updatePreferences(body: {
  target_titles?: string[];
  target_locations?: string[];
  remote_preference?: string;
  salary_floor?: number;
  industries?: string[];
  company_size_preference?: string;
  seniority_level?: string;
}) {
  return request('/api/v1/profile/preferences', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export async function uploadResume(file: File) {
  const form = new FormData();
  form.append('file', file);
  const url = `${API_BASE}/api/v1/profile/resume/upload`;
  const token = await getAccessToken();
  const res = await fetch(url, {
    method: 'POST',
    body: form,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(text, res.status);
  }
  return res.json();
}

// ─── Settings ───

export async function getSettings() {
  return request('/api/v1/settings');
}

export async function updateAutopilot(body: { enabled?: boolean; threshold?: number; daily_limit?: number }) {
  return request('/api/v1/settings/autopilot', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export async function updateNotifications(body: { channels?: string[]; on_apply?: boolean; daily_digest?: boolean }) {
  return request('/api/v1/settings/notifications', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export async function updateBlocklist(body: { blacklist?: string[]; whitelist?: string[] }) {
  return request('/api/v1/settings/blocklist', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

// ─── Matches ───

export async function getMatches(params?: { min_score?: number; page?: number; per_page?: number }) {
  const qs = new URLSearchParams();
  if (params?.min_score) qs.set('min_score', String(params.min_score));
  if (params?.page) qs.set('page', String(params.page));
  if (params?.per_page) qs.set('per_page', String(params.per_page));
  const query = qs.toString();
  return request<{
    items: Array<{
      match_id: string;
      match_score: number;
      job: { id: string; title: string; company: string; location: string; remote_type: string | null; ats_type: string; apply_url: string };
    }>;
    page: number;
    per_page: number;
  }>(`/api/v1/matches${query ? `?${query}` : ''}`);
}

// ─── Applications ───

export async function listApplications(params?: { status?: string; page?: number; per_page?: number }) {
  const qs = new URLSearchParams();
  if (params?.status) qs.set('status', params.status);
  if (params?.page) qs.set('page', String(params.page));
  if (params?.per_page) qs.set('per_page', String(params.per_page));
  const query = qs.toString();
  return request<{
    items: Array<{
      id: string;
      status: string;
      trigger: string;
      job: { id: string; title: string; company: string; ats_type: string };
      tinyfish_status: string | null;
      screenshot_url: string | null;
      submitted_at: string | null;
      created_at: string | null;
    }>;
    total: number;
    page: number;
    per_page: number;
  }>(`/api/v1/applications${query ? `?${query}` : ''}`);
}

export async function getApplicationStats() {
  return request<{
    total: number;
    submitted: number;
    confirmed: number;
    failed: number;
    needs_manual: number;
    in_progress: number;
    this_month: number;
    monthly_limit: number;
    tier: string;
  }>('/api/v1/applications/stats');
}

// ─── Agent ───

export async function agentSync(message: string, sessionId?: string) {
  return request<{
    response: string;
    session_id: string;
    tool_calls: Array<{ tool: string; input: Record<string, unknown> }>;
    tool_results: Array<{ tool: string; result: Record<string, unknown> }>;
  }>('/api/v1/agent/sync', {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId, channel: 'web' }),
  });
}

export async function getAgentHistory(sessionId?: string) {
  const params = new URLSearchParams();
  if (sessionId) params.set('session_id', sessionId);
  return request(`/api/v1/agent/history?${params}`);
}

// ─── Waitlist ───

export async function joinWaitlist(email: string, referralSource?: string) {
  return request<{ status: string; message: string }>('/v1/waitlist', {
    method: 'POST',
    body: JSON.stringify({ email, referral_source: referralSource }),
  });
}

export async function getWaitlistCount() {
  return request<{ count: number }>('/v1/waitlist/count');
}

export { ApiError };
