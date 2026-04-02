'use client';

import { useCallback, useRef, useState } from 'react';
import { getAccessToken } from '@/lib/supabase';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

// ---------------------------------------------------------------------------
// Types — mirror the SSE event payloads from the recon spec
// ---------------------------------------------------------------------------

export interface ReconCareersData {
  open_roles: number;
  technologies: string[];
  top_departments: string[];
  hiring_velocity: 'growing' | 'stable' | 'slowing';
}

export interface ReconCompanyData {
  mission: string;
  founded: string;
  size: string;
  locations: string[];
  funding: string;
  notable_facts: string[];
}

export interface ReconPostingData {
  tech_stack: string[];
  requirements: string[];
  seniority: string;
  location?: string | null;
  remote_type?: string | null;
}

export interface ReconSynthesisData {
  summary: string;
  hiring_velocity: string;
  tech_stack: string[];
  team_insight: string;
  insider_tip: string;
  confidence: 'high' | 'medium' | 'low';
}

export interface ReconDoneData {
  dossier_id: string;
  cached: boolean;
  duration_ms: number;
}

export type ReconSectionStatus = 'idle' | 'loading' | 'done' | 'error';

export type ReconOverallStatus =
  | 'idle'
  | 'connecting'
  | 'streaming'
  | 'done'
  | 'error';

export interface ReconState {
  careers: { status: ReconSectionStatus; data: ReconCareersData | null; error: string | null };
  company: { status: ReconSectionStatus; data: ReconCompanyData | null; error: string | null };
  posting: { status: ReconSectionStatus; data: ReconPostingData | null; error: string | null };
  synthesis: { status: ReconSectionStatus; data: ReconSynthesisData | null; error: string | null };
  overall: ReconOverallStatus;
  errorMessage: string | null;
  cached: boolean;
  durationMs: number | null;
}

const INITIAL_STATE: ReconState = {
  careers: { status: 'idle', data: null, error: null },
  company: { status: 'idle', data: null, error: null },
  posting: { status: 'idle', data: null, error: null },
  synthesis: { status: 'idle', data: null, error: null },
  overall: 'idle',
  errorMessage: null,
  cached: false,
  durationMs: null,
};

const DEVICE_ID_KEY = 'foxhound_device_id';

function getOrCreateDeviceId(): string | null {
  try {
    const existing = window.localStorage.getItem(DEVICE_ID_KEY);
    if (existing) return existing;
    const next =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `dev-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.localStorage.setItem(DEVICE_ID_KEY, next);
    return next;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useRecon() {
  const [state, setState] = useState<ReconState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(INITIAL_STATE);
  }, []);

  const start = useCallback(async (jobId: string) => {
    // Abort any existing stream
    abortRef.current?.abort();

    const controller = new AbortController();
    abortRef.current = controller;

    // Set all sections to loading, overall to connecting
    setState({
      careers: { status: 'loading', data: null, error: null },
      company: { status: 'loading', data: null, error: null },
      posting: { status: 'loading', data: null, error: null },
      synthesis: { status: 'loading', data: null, error: null },
      overall: 'connecting',
      errorMessage: null,
      cached: false,
      durationMs: null,
    });

    try {
      const token = await getAccessToken();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const deviceId = getOrCreateDeviceId();
      if (deviceId) headers['X-Foxhound-Device-Id'] = deviceId;

      const res = await fetch(`${API_BASE}/api/v1/recon/${jobId}`, {
        method: 'POST',
        headers,
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        throw new Error(`Quick report request failed (${res.status})`);
      }

      setState((prev) => ({ ...prev, overall: 'streaming' }));

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let eventType = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr);
              handleEvent(eventType, data);
            } catch {
              // Skip malformed JSON
            }
            eventType = '';
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      // Keep UI messaging generic; detailed diagnostics are logged on the backend.
      setState((prev) => ({
        ...prev,
        overall: 'error',
        errorMessage: 'Quick report failed. Try again later.',
      }));
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    }
  }, []);

  function handleEvent(type: string, data: Record<string, unknown>) {
    switch (type) {
      case 'status':
        // Initial status event — sections are already in loading state
        break;

      case 'posting':
        setState((prev) => ({
          ...prev,
          posting: { status: 'done', data: data as unknown as ReconPostingData, error: null },
        }));
        break;

      case 'careers':
        setState((prev) => ({
          ...prev,
          careers: { status: 'done', data: data as unknown as ReconCareersData, error: null },
        }));
        break;

      case 'company':
        setState((prev) => ({
          ...prev,
          company: { status: 'done', data: data as unknown as ReconCompanyData, error: null },
        }));
        break;

      case 'synthesis':
        setState((prev) => ({
          ...prev,
          synthesis: { status: 'done', data: data as unknown as ReconSynthesisData, error: null },
        }));
        break;

      case 'error': {
        const source = data.source as string;
        if (source === 'careers' || source === 'company' || source === 'posting' || source === 'synthesis') {
          setState((prev) => ({
            ...prev,
            [source]: { status: 'error' as ReconSectionStatus, data: null, error: (data.reason as string) || 'unavailable' },
          }));
        }
        break;
      }

      case 'done': {
        const doneData = data as unknown as ReconDoneData;
        setState((prev) => ({
          ...prev,
          overall: 'done',
          cached: doneData.cached ?? false,
          durationMs: doneData.duration_ms ?? null,
        }));
        break;
      }
    }
  }

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState((prev) => ({ ...prev, overall: prev.overall === 'idle' ? 'idle' : 'done' }));
  }, []);

  return { state, start, abort, reset };
}
