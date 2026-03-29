/**
 * Implicit feedback collection for ML ranking.
 *
 * Buffers interaction events and flushes them in batches to the backend
 * every 5 seconds or on page unload via navigator.sendBeacon.
 */

const BUFFER_FLUSH_INTERVAL = 5000;
const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

interface InteractionEvent {
  session_id: string;
  opportunity_id: string;
  event_type: string;
  query_context?: string;
  display_position?: number;
  payload?: Record<string, unknown>;
  ranker_variant?: string;
}

const buffer: InteractionEvent[] = [];
let sessionId: string | null = null;

function getSessionId(): string {
  if (typeof window === 'undefined') return 'ssr';
  if (!sessionId) {
    sessionId = sessionStorage.getItem('fh_session') || crypto.randomUUID();
    sessionStorage.setItem('fh_session', sessionId);
  }
  return sessionId;
}

export function trackEvent(
  opportunityId: string,
  eventType: string,
  extra?: Partial<Omit<InteractionEvent, 'session_id' | 'opportunity_id' | 'event_type'>>,
) {
  if (typeof window === 'undefined') return;
  buffer.push({
    session_id: getSessionId(),
    opportunity_id: opportunityId,
    event_type: eventType,
    ...extra,
  });
}

/**
 * Track an impression when an element enters the viewport for > 1 second.
 * Returns a cleanup function to disconnect the observer.
 */
export function trackImpression(
  element: HTMLElement | null,
  opportunityId: string,
  displayPosition?: number,
): (() => void) | undefined {
  if (!element || typeof IntersectionObserver === 'undefined') return undefined;

  let timer: ReturnType<typeof setTimeout> | null = null;
  let tracked = false;

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && !tracked) {
          timer = setTimeout(() => {
            trackEvent(opportunityId, 'impression', { display_position: displayPosition });
            tracked = true;
          }, 1000);
        } else if (!entry.isIntersecting && timer) {
          clearTimeout(timer);
          timer = null;
        }
      }
    },
    { threshold: 0.5 },
  );

  observer.observe(element);
  return () => {
    if (timer) clearTimeout(timer);
    observer.disconnect();
  };
}

/**
 * Track detail page engagement: dwell time, scroll depth, bounce.
 * Call on mount, returns cleanup function for unmount.
 */
export function trackDetailEngagement(
  opportunityId: string,
): () => void {
  const startTime = Date.now();
  let maxScrollPct = 0;
  const visitKey = `fh_visited_${opportunityId}`;
  const isReturn = !!sessionStorage.getItem(visitKey);
  sessionStorage.setItem(visitKey, '1');

  if (isReturn) {
    trackEvent(opportunityId, 'return_visit');
  }

  const onScroll = () => {
    const scrollTop = window.scrollY;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    if (docHeight > 0) {
      maxScrollPct = Math.max(maxScrollPct, scrollTop / docHeight);
    }
  };

  window.addEventListener('scroll', onScroll, { passive: true });

  return () => {
    window.removeEventListener('scroll', onScroll);
    const dwellMs = Date.now() - startTime;

    if (dwellMs < 3000) {
      trackEvent(opportunityId, 'bounce');
    } else {
      trackEvent(opportunityId, 'detail_dwell', {
        payload: { dwell_ms: dwellMs },
      });
    }

    if (maxScrollPct > 0.1) {
      trackEvent(opportunityId, 'detail_scroll', {
        payload: { scroll_pct: Math.round(maxScrollPct * 100) / 100 },
      });
    }
  };
}

function flush() {
  if (buffer.length === 0) return;
  const events = buffer.splice(0, 50);
  const body = JSON.stringify({ events });

  if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
    navigator.sendBeacon(
      `${API_BASE}/v1/feedback/events`,
      new Blob([body], { type: 'application/json' }),
    );
  } else if (typeof fetch !== 'undefined') {
    fetch(`${API_BASE}/v1/feedback/events`, {
      method: 'POST',
      body,
      headers: { 'Content-Type': 'application/json' },
      keepalive: true,
    }).catch(() => {});
  }
}

// Auto-flush setup (client-side only)
if (typeof window !== 'undefined') {
  setInterval(flush, BUFFER_FLUSH_INTERVAL);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
}
