import { useQuery } from '@tanstack/react-query';
import { accountApi, SESSION_KEY } from './api';

export function useAccountSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: ({ signal }) => accountApi.session(signal),
    staleTime: 0,
    retry: false,
  });
}

export function safeReturnTo(value: string | null) {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\r\n]/.test(value)) {
    return '/';
  }
  const pathname = value.split('?')[0] ?? '';
  return ['/', '/review', '/bookings', '/account/mfa'].includes(pathname) ||
    /^\/admin(?:\/[a-zA-Z0-9/-]*)?$/.test(pathname) ||
    /^\/rooms\/[a-fA-F0-9-]+$/.test(pathname)
    ? value
    : '/';
}
