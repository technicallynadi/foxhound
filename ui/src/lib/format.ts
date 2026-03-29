/** Normalize a backend tag/vertical string for display.
 *  "ai_developer_tooling" → "AI Developer Tooling"
 *  "devtools" → "Devtools"
 *  "healthtech" → "Healthtech"  */
export function formatTag(raw: string | null | undefined): string {
  if (!raw) return '';
  return raw
    .replace(/_/g, ' ')
    .replace(/\bai\b/gi, 'AI')
    .replace(/\bapi\b/gi, 'API')
    .replace(/\bmcp\b/gi, 'MCP')
    .replace(/\bml\b/gi, 'ML')
    .replace(/\bui\b/gi, 'UI')
    .replace(/\bux\b/gi, 'UX')
    .split(' ')
    .map((w) => {
      if (w === w.toUpperCase() && w.length <= 3) return w; // keep acronyms
      return w.charAt(0).toUpperCase() + w.slice(1);
    })
    .join(' ');
}

const EFFORT_LABELS: Record<string, string> = {
  weekend: 'Weekend Build',
  side_project: 'Side Project',
  startup: 'Startup Idea',
  feature_gap: 'Feature Gap',
};

export function formatEffortTier(tier: string | null | undefined): string {
  if (!tier) return '';
  return EFFORT_LABELS[tier] || formatTag(tier);
}

const FORM_FACTOR_LABELS: Record<string, string> = {
  cli_tool: 'CLI Tool',
  browser_extension: 'Browser Extension',
  github_action: 'GitHub Action',
  api_service: 'API Service',
  saas_app: 'SaaS App',
  mobile_app: 'Mobile App',
  agent_skill: 'Agent Skill',
  vscode_extension: 'VS Code Extension',
  slack_bot: 'Slack Bot',
  webhook: 'Webhook',
};

export function formatFormFactor(ff: string | null | undefined): string {
  if (!ff) return '';
  return FORM_FACTOR_LABELS[ff] || formatTag(ff);
}

export function formatElapsed(start: string | null | undefined): string {
  if (!start) return '';
  const ms = Date.now() - new Date(start).getTime();
  if (ms < 0) return 'just now';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

export function formatTimeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  const ms = Date.now() - new Date(dateStr).getTime();
  if (ms < 0) return 'just now';
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
