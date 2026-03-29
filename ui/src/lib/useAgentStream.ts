'use client';

import { useCallback, useRef, useState } from 'react';
import { getAccessToken } from '@/lib/supabase';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolName?: string;
  toolResult?: Record<string, unknown>;
  channel?: string;
  createdAt: string;
}

export interface ToolCall {
  toolName: string;
  toolInput: Record<string, unknown>;
}

export interface ToolResult {
  toolName: string;
  data: Record<string, unknown>;
  message: string;
}

export type StreamState = 'idle' | 'streaming' | 'tool_executing' | 'error';

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAgentStream(userId: string) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [streamState, setStreamState] = useState<StreamState>('idle');
  const [activeToolResult, setActiveToolResult] = useState<ToolResult | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const msgIdCounter = useRef(0);

  const nextId = () => `msg_${Date.now()}_${++msgIdCounter.current}`;

  // Load history from API
  const loadHistory = useCallback(async () => {
    try {
      const token = await getAccessToken();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(
        `${API_BASE}/api/v1/agent/history?user_id=${userId}${sessionId ? `&session_id=${sessionId}` : ''}`,
        { headers },
      );
      if (!res.ok) return;
      const data = await res.json();
      if (data.session_id) setSessionId(data.session_id);
      if (data.messages) {
        setMessages(
          data.messages.map((m: Record<string, string>) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            channel: m.channel,
            createdAt: m.created_at,
          })),
        );
      }
    } catch {
      // Silently fail — user will see empty chat
    }
  }, [userId, sessionId]);

  // Send a message and stream the response
  const send = useCallback(
    async (content: string) => {
      if (!content.trim()) return;

      // Optimistic: add user message immediately
      const userMsg: AgentMessage = {
        id: nextId(),
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);

      // Prepare assistant message placeholder
      const assistantId = nextId();
      setMessages((prev) => [
        ...prev,
        { id: assistantId, role: 'assistant', content: '', createdAt: new Date().toISOString() },
      ]);

      setStreamState('streaming');
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const token = await getAccessToken();
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE}/api/v1/agent`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            message: content,
            user_id: userId,
            session_id: sessionId,
            channel: 'web',
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`Agent API error: ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let eventType = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              try {
                const data = JSON.parse(dataStr);
                handleSSEEvent(eventType, data, assistantId);
              } catch {
                // Skip malformed JSON
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          const errorMsg = (err as Error).message || 'Something went wrong. Try again.';
          console.error('Agent stream error:', errorMsg);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: m.content || `Could not reach Foxhound. ${errorMsg}` }
                : m,
            ),
          );
        }
      } finally {
        setStreamState('idle');
        abortRef.current = null;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [userId, sessionId],
  );

  const handleSSEEvent = (type: string, data: Record<string, unknown>, assistantId: string) => {
    switch (type) {
      case 'text_delta':
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + (data.text as string) } : m,
          ),
        );
        break;

      case 'tool_call_start':
        setStreamState('tool_executing');
        // Add a tool-executing indicator to the assistant message
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, toolName: data.tool_name as string }
              : m,
          ),
        );
        break;

      case 'tool_result': {
        setStreamState('streaming');
        const result: ToolResult = {
          toolName: data.tool_name as string,
          data: (data.data || {}) as Record<string, unknown>,
          message: (data.message || '') as string,
        };
        setActiveToolResult(result);

        // Append tool result as a separate message for rendering
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: 'assistant',
            content: '',
            toolName: result.toolName,
            toolResult: result.data,
            createdAt: new Date().toISOString(),
          },
        ]);
        break;
      }

      case 'done':
        if (data.session_id) setSessionId(data.session_id as string);
        setStreamState('idle');
        break;

      case 'error':
        setStreamState('error');
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: (data.message as string) || 'An error occurred.' }
              : m,
          ),
        );
        break;
    }
  };

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setStreamState('idle');
  }, []);

  return {
    messages,
    streamState,
    activeToolResult,
    sessionId,
    send,
    abort,
    loadHistory,
  };
}
