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

export type ActionPriority = 'low' | 'normal' | 'high';

export interface ApplicationContextContract {
  application_id: string;
  job_id: string | null;
  company: string;
  role: string;
  status: string;
  posting_status: string;
  submitted_at: string | null;
  days_since_applied: number;
  followup_day3_sent: boolean;
  followup_day7_sent: boolean;
  followup_day14_sent: boolean;
  brief_ready: boolean;
  brief_status: string | null;
}

export interface RecommendedNextActionContract {
  label: string;
  detail: string;
  href: string | null;
  href_label: string | null;
  priority: ActionPriority;
}

export type IntelligenceResponse = Record<string, unknown> & {
  application_context: ApplicationContextContract | null;
  recommended_next_action: RecommendedNextActionContract;
};

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
    resume_filename?: string | null;
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

export async function bootstrapProfile(body: {
  target_titles?: string[];
  target_locations?: string[];
  remote_preference?: string;
  salary_floor?: number;
  industries?: string[];
  seniority_level?: string;
  first_name?: string;
  last_name?: string;
  location?: string;
}) {
  return request('/api/v1/profile/bootstrap', {
    method: 'POST',
    body: JSON.stringify(body),
  });
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
      brief_ready: boolean;
      brief_status?: string | null;
      job: { id: string; title: string; company: string; ats_type: string };
      tinyfish_status: string | null;
      posting_status?: string | null;
      posting_diff_summary?: string | null;
      last_watchdog_check_at?: string | null;
      screenshot_url: string | null;
      pre_submit_screenshot_url?: string | null;
      submitted_at: string | null;
      created_at: string | null;
    }>;
    total: number;
    page: number;
    per_page: number;
  }>(`/api/v1/applications${query ? `?${query}` : ''}`);
}

export async function trackManualApplication(body: {
  company: string;
  title: string;
  apply_url: string;
  location?: string;
  notes?: string;
  submitted_at?: string;
}) {
  return request<{
    application_id: string;
    status: string;
    trigger: string;
    job_id: string;
  }>('/api/v1/applications/manual-track', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function archiveApplication(applicationId: string) {
  return request<{ ok: boolean; application_id: string; status: string }>(
    `/api/v1/applications/${applicationId}/archive`,
    { method: 'PATCH' },
  );
}

export async function getPendingQuestions(applicationId: string) {
  return request<{
    application_id: string;
    questions: Array<{
      index: number;
      question: string;
      field_type: string;
      category: string;
      suggested_answer?: string;
      options?: string[];
    }>;
  }>(`/api/v1/applications/${applicationId}/questions`);
}

export async function submitAnswers(applicationId: string, answers: Array<{ index: number; action: string; answer?: string }>) {
  return request<Record<string, unknown>>(`/api/v1/applications/${applicationId}/questions/answer`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
  });
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

// Watchdog
export interface WatchdogApplication {
  application_id: string;
  company: string;
  title: string;
  status: string;
  posting_status: string;
  last_watchdog_check_at: string | null;
  posting_diff_summary: string | null;
  applied_at: string | null;
}

export async function getWatchdogStatus() {
  return request<{ applications: WatchdogApplication[] } | WatchdogApplication[]>('/api/v1/watchdog/status');
}

export async function triggerWatchdogCheck(applicationId: string) {
  return request<{ status: string }>(`/api/v1/watchdog/check/${applicationId}`, { method: 'POST' });
}

// ─── Dossier ───

export async function createDossier(applicationId: string) {
  return request<{ dossier_id: string; status: string }>(`/api/v1/dossier/${applicationId}`, {
    method: 'POST',
  });
}

export async function getDossier(dossierId: string) {
  return request<{
    id: string;
    application_id: string;
    company_normalized: string;
    status: string;
    instant_analysis: Record<string, unknown> | null;
    company_data: Record<string, unknown> | null;
    careers_data: Record<string, unknown> | null;
    news_data: Array<Record<string, unknown>> | null;
    team_contacts: Array<Record<string, unknown>> | null;
    outreach_draft: Record<string, unknown> | null;
    interview_prep: Record<string, unknown> | null;
    overall_assessment: string | null;
    sources_completed: string[];
    sources_failed: string[];
    created_at: string;
    completed_at: string | null;
    company_name?: string;
    role_title?: string;
  }>(`/api/v1/dossier/${dossierId}`);
}

export async function getDossierByApplication(applicationId: string) {
  return request<{
    id: string;
    status: string;
  } | null>(`/api/v1/dossier/by-application/${applicationId}`);
}

export async function resynthesizeDossier(dossierId: string) {
  return request<{ status: string; dossier_id: string }>(`/api/v1/dossier/${dossierId}/resynthesize`, {
    method: 'POST',
  });
}

export async function getPendingReportNotifications() {
  return request<{
    notifications: Array<{
      dossier_id: string;
      company: string;
      role: string;
      status: string;
      completed_at: string | null;
    }>;
  }>('/api/v1/dossier/notifications/pending');
}

export async function dismissReportNotification(dossierId: string) {
  return request<{ ok: boolean }>(`/api/v1/dossier/${dossierId}/dismiss`, {
    method: 'POST',
  });
}

// ─── Intelligence Hub ───

export async function runInterviewPrep(companyName: string, role?: string, applicationId?: string) {
  return request<IntelligenceResponse>('/api/v1/intelligence/interview-prep', {
    method: 'POST',
    body: JSON.stringify({ company_name: companyName, role: role || '', application_id: applicationId || null }),
  });
}

export async function runCompanyBrief(companyName: string, applicationId?: string) {
  return request<IntelligenceResponse>('/api/v1/intelligence/company-brief', {
    method: 'POST',
    body: JSON.stringify({ company_name: companyName, application_id: applicationId || null }),
  });
}

export async function runPeopleResearch(companyName: string, role?: string, applicationId?: string) {
  return request<IntelligenceResponse>('/api/v1/intelligence/people-research', {
    method: 'POST',
    body: JSON.stringify({ company_name: companyName, role: role || '', application_id: applicationId || null }),
  });
}

export async function runJobDiscovery(query: string, role?: string, location?: string, industry?: string, applicationId?: string) {
  return request<IntelligenceResponse>('/api/v1/intelligence/discover', {
    method: 'POST',
    body: JSON.stringify({
      query,
      role: role || '',
      location: location || '',
      industry: industry || '',
      application_id: applicationId || null,
    }),
  });
}

// ─── Activity Feed + Command Center ───

export async function getActivityFeed(page = 1, pageSize = 20, eventType?: string) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (eventType) params.set('event_type', eventType);
  return request<{
    events: Array<{
      id: string;
      type: string;
      title: string;
      description?: string;
      timestamp: string;
      metadata?: Record<string, unknown>;
    }>;
    page: number;
    total: number;
    has_more: boolean;
  }>(`/api/v1/activity?${params}`);
}

export async function getMorningBriefing() {
  return request<{
    generated_at: string;
    period_start: string;
    summary: {
      jobs_discovered: number;
      matches_above_threshold: number;
      applications_submitted: number;
      alerts_count: number;
      questions_pending: number;
    };
    applications: Array<{
      application_id: string;
      company: string;
      title: string;
      match_score: number | null;
      submitted_at: string | null;
      status: string;
      brief_ready: boolean;
      brief_id: string | null;
    }>;
    alerts: Array<{
      type: string;
      title: string;
      description: string;
      metadata?: Record<string, unknown>;
    }>;
    new_matches: Array<{
      match_id: string;
      job_id: string;
      company: string;
      title: string;
      match_score: number;
    }>;
  }>('/api/v1/activity/briefing');
}

export async function getDashboardStats() {
  return request<{
    total_matches: number;
    total_applications: number;
    autopilot_enabled: boolean;
    autopilot_threshold: number;
    applications_this_month: number;
    monthly_limit: number;
  }>('/api/v1/activity/stats');
}

export async function getBrief(applicationId: string) {
  return request<{
    brief_id: string;
    application_id: string;
    status: string;
    company: string;
    title: string;
    match_score: number | null;
    applied_at: string | null;
    generated_at: string | null;
    application_context: ApplicationContextContract;
    submission: {
      status: string;
      method: string;
      ats_type: string;
      screenshot: string | null;
      pre_submit_screenshot: string | null;
      fields_filled: string[];
    };
    posting_status: {
      watchdog_status: string;
      ghost_score: number | null;
      ghost_risk: string | null;
    };
    company_brief: Record<string, unknown> | null;
    pathfinder: Record<string, unknown> | null;
    network_map: Record<string, unknown> | null;
    dossier: Record<string, unknown> | null;
    recommended_next_action: RecommendedNextActionContract;
  }>(`/api/v1/brief/${applicationId}`);
}

export { ApiError };
