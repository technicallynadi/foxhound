'use client';

import { useState, useEffect, useCallback } from 'react';

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trigger, setTrigger] = useState(0);

  const refetch = useCallback(() => setTrigger((t) => t + 1), []);

  useEffect(() => {
    let canceled = false;
    setLoading(true);
    setError(null);

    fetcher()
      .then((result) => {
        if (!canceled) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!canceled) {
          let message = err?.message || 'Something went wrong';
          if (message === 'Failed to fetch' || message.includes('NetworkError') || message.includes('ECONNREFUSED')) {
            message = 'Could not connect to Foxhound. Make sure the server is running.';
          }
          setError(message);
          setLoading(false);
        }
      });

    return () => {
      canceled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger, ...deps]);

  return { data, loading, error, refetch };
}

interface UseMutationResult<T, P> {
  data: T | null;
  loading: boolean;
  error: string | null;
  mutate: (params: P) => Promise<T | null>;
  reset: () => void;
}

export function useMutation<T, P = void>(
  fn: (params: P) => Promise<T>
): UseMutationResult<T, P> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mutate = useCallback(
    async (params: P): Promise<T | null> => {
      setLoading(true);
      setError(null);
      try {
        const result = await fn(params);
        setData(result);
        setLoading(false);
        return result;
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Something went wrong';
        setError(message);
        setLoading(false);
        return null;
      }
    },
    [fn]
  );

  const reset = useCallback(() => {
    setData(null);
    setError(null);
    setLoading(false);
  }, []);

  return { data, loading, error, mutate, reset };
}
