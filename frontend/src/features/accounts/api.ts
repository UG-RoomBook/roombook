import { z } from 'zod';
import { ApiError } from '@/shared/api/client';
import { createClient } from '@/shared/api/generated/client';
import {
  changeAccountEmail,
  getCurrentSession,
  getRecoverySession,
  loginAccount,
  logoutCurrentSession,
  registerAccount,
  requestAccountRecovery,
  resendAccountVerification,
  resetAccountPassword,
} from '@/shared/api/generated/sdk.gen';

export const accountClient = createClient({
  baseUrl: globalThis.location?.origin || 'http://localhost',
  credentials: 'same-origin',
  fetch: (input, init) => globalThis.fetch(input, init),
});
export const sessionSchema = z.object({
  user: z.object({ id: z.uuid(), role: z.enum(['Member', 'Admin']) }),
  aal: z.enum(['aal1', 'aal2']),
  purpose: z.literal('standard'),
  csrf_token: z.string().min(1),
  expires_at: z.string(),
  mfa_verified_at: z.string().nullable().optional(),
});
const messageSchema = z.object({ message: z.string().max(500) });
export type AccountSession = z.infer<typeof sessionSchema>;
export const SESSION_KEY = ['identity', 'session'] as const;

export async function run<T>(
  call: (signal: AbortSignal) => Promise<{ data?: unknown; error?: unknown; response?: Response }>,
  schema: z.ZodType<T>,
  parent?: AbortSignal,
): Promise<T> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), 15_000);
  try {
    const signal = parent ? AbortSignal.any([parent, timeout.signal]) : timeout.signal;
    const result = await call(signal);
    if (!result.response?.ok) {
      const failure = z
        .object({ error: z.object({ message: z.string(), code: z.string() }) })
        .safeParse(result.error);
      throw new ApiError(failure.success ? failure.data.error.message : 'The request failed.', {
        status: result.response?.status,
        code: failure.success ? failure.data.error.code : 'ACCOUNT_ERROR',
      });
    }
    const parsed = schema.safeParse(result.response.status === 204 ? undefined : result.data);
    if (!parsed.success)
      throw new ApiError('The response could not be verified. Retry the same request.');
    return parsed.data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('The service could not be reached. Check your connection and try again.');
  } finally {
    clearTimeout(timer);
  }
}

export const accountApi = {
  session: async (signal?: AbortSignal) => {
    try {
      return await run(
        (s) => getCurrentSession({ client: accountClient, signal: s, cache: 'no-store' }),
        sessionSchema,
        signal,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }
  },
  login: (body: { email: string; password: string }) =>
    run((signal) => loginAccount({ client: accountClient, signal, body }), sessionSchema),
  register: (body: { email: string; password: string }) =>
    run((signal) => registerAccount({ client: accountClient, signal, body }), messageSchema),
  recover: (email: string) =>
    run(
      (signal) => requestAccountRecovery({ client: accountClient, signal, body: { email } }),
      messageSchema,
    ),
  resend: (email: string) =>
    run(
      (signal) => resendAccountVerification({ client: accountClient, signal, body: { email } }),
      messageSchema,
    ),
  recovery: (signal?: AbortSignal) =>
    run(
      (s) => getRecoverySession({ client: accountClient, signal: s, cache: 'no-store' }),
      z.object({ csrf_token: z.string().min(1) }),
      signal,
    ),
  reset: (password: string, csrf: string) =>
    run(
      (signal) =>
        resetAccountPassword({
          client: accountClient,
          signal,
          body: { password },
          headers: { 'X-CSRF-Token': csrf },
        }),
      messageSchema,
    ),
  email: (email: string, csrf: string) =>
    run(
      (signal) =>
        changeAccountEmail({
          client: accountClient,
          signal,
          body: { email },
          headers: { 'X-CSRF-Token': csrf },
        }),
      messageSchema,
    ),
  logout: (csrf: string) =>
    run(
      (signal) =>
        logoutCurrentSession({ client: accountClient, signal, headers: { 'X-CSRF-Token': csrf } }),
      z.undefined(),
    ),
};
