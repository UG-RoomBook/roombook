import { z } from 'zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, createdBookingSchema, type CreatedBooking } from '@/shared/api/client';
import type { CreateBooking } from '@/shared/api/types';
import { accountApi, SESSION_KEY } from '@/features/accounts/api';

const attemptSchema = z.object({
  ownerId: z.string().uuid(),
  key: z.string().uuid(),
  body: z.object({ room_id: z.string().uuid(), starts_at: z.string(), ends_at: z.string() }),
  state: z.enum(['pending', 'rejected', 'confirmed']),
  receipt: createdBookingSchema.optional(),
});
export type BookingAttempt = z.infer<typeof attemptSchema>;

// Per-tab persistence survives reload and same-user sign-in. Never store credentials.
// Keep successful keys too: revisiting review must not create a second reservation.
export function attemptSlot(ownerId: string, body: CreateBooking) {
  return `roombook.booking.v1:${ownerId}:${body.room_id}:${Date.parse(body.starts_at)}:${Date.parse(body.ends_at)}`;
}
export function loadAttempt(ownerId: string, body: CreateBooking): BookingAttempt | null {
  try {
    const raw = sessionStorage.getItem(attemptSlot(ownerId, body));
    if (!raw) return null;
    const value = attemptSchema.parse(JSON.parse(raw));
    if (
      attemptSlot(value.ownerId, value.body) !== attemptSlot(ownerId, body) ||
      (value.receipt &&
        (value.receipt.owner_id !== ownerId ||
          value.receipt.room_id !== body.room_id ||
          Date.parse(value.receipt.starts_at) !== Date.parse(body.starts_at) ||
          Date.parse(value.receipt.ends_at) !== Date.parse(body.ends_at)))
    )
      throw new Error();
    return value;
  } catch {
    throw new ApiError(
      'Your saved booking attempt could not be read. Keep this tab and contact support before booking this time again.',
      { code: 'ATTEMPT_STORAGE' },
    );
  }
}
export function saveAttempt(attempt: BookingAttempt) {
  try {
    const slot = attemptSlot(attempt.ownerId, attempt.body);
    const value = JSON.stringify(attempt);
    sessionStorage.setItem(slot, value);
    if (sessionStorage.getItem(slot) !== value) throw new Error();
  } catch {
    throw new ApiError(
      'This browser cannot save a safe booking attempt. Enable session storage before confirming.',
      { code: 'ATTEMPT_STORAGE' },
    );
  }
}

export function useCreateBooking() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ['bookings', 'create'],
    retry: false,
    mutationFn: async ({
      ownerId,
      body,
    }: {
      ownerId: string;
      body: CreateBooking;
    }): Promise<CreatedBooking> => {
      // Revalidate before each explicit attempt, including reconciliation after sign-in.
      const session = await accountApi.session();
      client.setQueryData(SESSION_KEY, session);
      if (!session || session.user.id !== ownerId) {
        throw new ApiError('Sign in again to confirm this selection.', {
          status: 401,
          code: 'SESSION_CHANGED',
        });
      }
      const prior = loadAttempt(ownerId, body);
      if (prior?.state === 'confirmed' && prior.receipt) return prior.receipt;
      const attempt: BookingAttempt = prior ?? {
        ownerId,
        body,
        key: crypto.randomUUID(),
        state: 'pending',
      };
      saveAttempt({ ...attempt, state: 'pending' });
      let receipt: CreatedBooking;
      try {
        receipt = await api.createBooking({
          body: attempt.body,
          ownerId,
          csrfToken: session.csrf_token,
          idempotencyKey: attempt.key,
        });
      } catch (error) {
        // An auth/validation response to a retry does not disprove an earlier lost commit.
        if (prior?.state !== 'pending' && error instanceof ApiError && !error.uncertain) {
          saveAttempt({ ...attempt, state: 'rejected' });
        }
        if (error instanceof ApiError && error.status === 401)
          client.setQueryData(SESSION_KEY, null);
        throw error;
      }
      // If storage becomes unavailable after commit, keep the original pending key.
      // The confirmed response remains usable now; a reload can replay that key.
      try {
        saveAttempt({ ...attempt, state: 'confirmed', receipt });
      } catch {
        /* Same key retained. */
      }
      return receipt;
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['rooms'] });
      void client.invalidateQueries({ queryKey: ['bookings'] });
    },
  });
}
