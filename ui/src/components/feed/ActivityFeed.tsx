'use client';

const EVENT_COLORS: Record<string, string> = {
  application_submitted: 'var(--g)',
  application_skipped: 'var(--t3)',
  application_blocked: 'var(--warning)',
  application_failed: 'var(--error)',
  matches_discovered: 'var(--vl)',
  ghost_alert: 'var(--error)',
  followup_scheduled: 'var(--t3)',
  followup_sent: 'var(--warning)',
  followup_reminder: 'var(--warning)',
  interview_detected: 'var(--g)',
  watchdog_check: 'var(--t3)',
  questions_pending: 'var(--warning)',
  dossier_ready: 'var(--vl)',
  research_started: 'var(--vl)',
  research_completed: 'var(--g)',
  scan_completed: 'var(--t3)',
  briefing_sent: 'var(--t3)',
};

interface ActivityEvent {
  id: string;
  type: string;
  title: string;
  description?: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

interface ActivityFeedProps {
  events: ActivityEvent[];
  loading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  onAnswerQuestions?: (applicationId: string) => void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function formatDayLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const eventDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = (today.getTime() - eventDay.getTime()) / 86400000;
  if (diff === 0) return 'TODAY';
  if (diff === 1) return 'YESTERDAY';
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }).toUpperCase();
}

export default function ActivityFeed({ events, loading, hasMore, onLoadMore, onAnswerQuestions }: ActivityFeedProps) {
  if (!events.length && !loading) {
    return (
      <div style={{
        padding: '48px 0', textAlign: 'center',
        fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t3)',
      }}>
        No activity yet. Foxhound will show updates here as it works.
      </div>
    );
  }

  return (
    <div>
      {events.map((event, idx) => {
        const dayLabel = formatDayLabel(event.timestamp);
        const prevDay = idx > 0 ? formatDayLabel(events[idx - 1].timestamp) : '';
        const showDaySep = dayLabel !== prevDay;

        return (
          <div key={event.id}>
            {showDaySep && (
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)',
                textTransform: 'uppercase', letterSpacing: '0.1em',
                marginTop: 28, marginBottom: 12,
                paddingBottom: 8, borderBottom: '1px solid var(--b)',
              }}>
                {dayLabel}
              </div>
            )}

            <div style={{
              display: 'flex', gap: 12, padding: '10px 0',
              alignItems: 'flex-start',
            }}>
              {/* Dot */}
              <div style={{
                width: 6, height: 6, borderRadius: '50%', marginTop: 6, flexShrink: 0,
                background: EVENT_COLORS[event.type] || 'var(--t3)',
                boxShadow: event.type === 'ghost_alert' || event.type === 'interview_detected'
                  ? `0 0 8px ${EVENT_COLORS[event.type]}` : 'none',
              }} />

              {/* Timestamp */}
              <div style={{
                width: 72, flexShrink: 0,
                fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
                textAlign: 'right',
              }}>
                {formatTime(event.timestamp)}
              </div>

              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, color: 'var(--t)' }}>
                  {event.title}
                </div>
                {event.description && (
                  <div style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>
                    {event.description}
                  </div>
                )}
                {/* Action links based on event type */}
                {!!(event.metadata?.application_id) &&
                  ['dossier_ready', 'research_completed'].includes(event.type) && (
                    <a href={`/brief/${String(event.metadata.application_id)}`} style={{
                      fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
                      textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: 4,
                      display: 'inline-block',
                    }}>
                      View Brief
                    </a>
                  )}
                {/* Questions pending — user reviews via the top alert, not individual events */}
                {!!(event.metadata?.application_id) &&
                  event.type === 'application_submitted' && (
                    <a href="/applications" style={{
                      fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--vl)',
                      textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: 4,
                      display: 'inline-block',
                    }}>
                      Open Applications
                    </a>
                  )}
              </div>
            </div>
          </div>
        );
      })}

      {hasMore && (
        <button
          onClick={onLoadMore}
          disabled={loading}
          style={{
            display: 'block', margin: '24px auto', padding: '8px 24px',
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
            textTransform: 'uppercase', letterSpacing: '0.06em',
            background: 'transparent', border: '1px solid var(--b)',
            borderRadius: 6, cursor: 'pointer',
          }}
        >
          {loading ? 'Loading...' : 'Load more'}
        </button>
      )}
    </div>
  );
}
