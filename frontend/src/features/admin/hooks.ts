import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { ApiError } from '@/shared/api/client';
import { SESSION_KEY } from '@/features/accounts/api';
import { useAccountSession } from '@/features/accounts/session';

export function formatTime(value: string, options?: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat('en-AU', {
    timeZone: 'Australia/Melbourne',
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    ...options,
  }).format(new Date(value));
}

export function useAdminQuery<T>(
  key: readonly unknown[],
  queryFn: (signal: AbortSignal) => Promise<T>,
  refresh = false,
  refetchOnWindowFocus = true,
) {
  const cache = useQueryClient();
  const session = useAccountSession();
  const query = useQuery({
    queryKey: ['admin', session.data?.user.id, ...key],
    queryFn: ({ signal }) => queryFn(signal),
    enabled: !!session.data && session.data.user.role === 'Admin' && session.data.aal === 'aal2',
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus,
    refetchInterval: refresh ? 30_000 : false,
    refetchIntervalInBackground: false,
  });
  useEffect(() => {
    if (query.error instanceof ApiError && [401, 403].includes(query.error.status ?? 0)) {
      void cache.cancelQueries({ queryKey: ['admin'] }).then(() => {
        cache.removeQueries({ queryKey: ['admin'] });
        void cache.invalidateQueries({ queryKey: SESSION_KEY });
      });
    }
  }, [cache, query.error]);
  return query;
}

export function useFilters() {
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get('offset') || 0);
  const offset = Number.isInteger(raw) && raw >= 0 && raw <= 1_000_000 ? raw : 0;
  return {
    params,
    offset,
    search: (params.get('search') || '').slice(0, 120),
    set: (key: string, value: string) => {
      const next = new URLSearchParams(params);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== 'offset') next.delete('offset');
      setParams(next);
    },
  };
}
