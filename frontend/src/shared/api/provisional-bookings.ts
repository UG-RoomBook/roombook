import { z } from 'zod';
import { client } from './generated/client.gen';
import type { Pagination } from './types';

// History and cancellation await RB-17/RB-18. Creation uses the real generated API.
// This adapter preserves the reviewed UI's opt-in MSW demonstration and tests.
// Replace it with generated operations when the booking API is implemented.
export const bookingSchema = z.object({
  id: z.string().uuid(),
  room_id: z.string().uuid(),
  starts_at: z.string().datetime({ offset: true }),
  ends_at: z.string().datetime({ offset: true }),
  status: z.enum(['active', 'cancelled']),
  created_at: z.string().datetime({ offset: true }),
  cancelled_at: z.string().datetime({ offset: true }).nullable(),
});

export type Booking = z.infer<typeof bookingSchema>;
export interface BookingList {
  items: Booking[];
  total: number;
  limit: number;
  offset: number;
}

export const bookingListSchema = z.object({
  items: z.array(bookingSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive().max(100),
  offset: z.number().int().nonnegative(),
});

function isDemonstration() {
  return (
    import.meta.env.DEV &&
    (import.meta.env.MODE === 'test' || import.meta.env.VITE_ENABLE_MOCKS === 'true')
  );
}

function unavailable() {
  return Promise.resolve({
    error: {
      error: {
        code: 'FEATURE_NOT_AVAILABLE',
        message: 'Booking is not available yet. You can search rooms and check availability.',
      },
    },
    response: new Response(null, { status: 501 }),
  });
}

export const provisionalBookings = {
  list: (
    query: Pagination & { from: string; to: string; room_id?: string },
    signal: AbortSignal,
  ) =>
    isDemonstration()
      ? client.get({ url: '/api/v1/bookings', query: { ...query }, signal })
      : unavailable(),
  cancel: (id: string, signal: AbortSignal) =>
    isDemonstration()
      ? client.post({ url: '/api/v1/bookings/{id}/cancel', path: { id }, signal })
      : unavailable(),
};
