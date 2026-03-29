// Foxhound API types

export interface UserProfile {
  id: string;
  user_id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  location: string | null;
  summary: string | null;
  skills: string[];
  years_experience: number | null;
  tier: string;
  applications_this_month: number;
  monthly_limit: number;
  autopilot_enabled: boolean;
}

export interface Job {
  job_id: string;
  title: string;
  company: string;
  location: string;
  remote: string;
  salary_range: string;
  match_score?: number;
  ats?: string;
}

export interface Application {
  application_id: string;
  company: string;
  title: string;
  status: string;
  trigger: string;
  error?: string;
  created_at: string;
  submitted_at?: string;
  has_screenshot?: boolean;
}

export interface DashboardData {
  profile: {
    name: string;
    tier: string;
    applications_this_month: number;
    monthly_limit: number;
    autopilot_enabled: boolean;
    profile_complete: boolean;
  };
  applications: {
    total: number;
    by_status: Record<string, number>;
    recent: Application[];
  };
  matches: {
    total: number;
    top_score: number | null;
  };
  pending_questions: number;
}

export interface AgentResponse {
  response: string;
  session_id: string;
  tool_calls: Array<{ tool: string; input: Record<string, unknown> }>;
  tool_results: Array<{ tool: string; result: Record<string, unknown> }>;
  budget?: { iterations: number; total_tokens: number; estimated_cost: number };
}
