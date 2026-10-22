import { z } from 'zod';
import { client } from './generated/client.gen';
import {
  createBooking,
  getVersion,
  listRooms,
  getRoom,
  getRoomDayAvailability,
} from './generated/sdk.gen';
import { bookingListSchema, bookingSchema, provisionalBookings } from './provisional-bookings';
import type { CreateBooking, Pagination } from './types';
import { createClient } from './generated/client';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly uncertain: boolean;

  constructor(
    message: string,
    options: { status?: number; code?: string; requestId?: string; uncertain?: boolean } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status ?? 0;
    this.code = options.code ?? 'NETWORK_ERROR';
    this.requestId = options.requestId;
    this.uncertain = options.uncertain ?? false;
  }
}

const roomSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  location: z.string(),
  capacity: z.number().int().positive(),
  active: z.boolean(),
  available: z.boolean().optional(),
});
const timestampSchema = z.string().datetime({ offset: true });
const timeSchema = z.string().regex(/^(?:[01]\d|2[0-3]):(?:00|15|30|45)$/);
const roomDaySchema = z.object({
  room: roomSchema,
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  timezone: z.literal('Australia/Melbourne'),
  generated_at: timestampSchema,
  booking_window_ends_at: timestampSchema,
  slots: z.array(
    z
      .object({
        time: timeSchema,
        starts_at: timestampSchema.nullable(),
        available: z.boolean(),
        unavailable_reason: z
          .enum([
            'inactive',
            'schedule_unconfirmed',
            'past',
            'outside_horizon',
            'invalid_local_time',
            'unavailable',
          ])
          .nullable(),
        valid_ends: z.array(z.object({ time: timeSchema, ends_at: timestampSchema })),
      })
      .refine((slot) => slot.available === (slot.starts_at !== null && slot.valid_ends.length > 0)),
  ),
});
export type RoomDay = z.infer<typeof roomDaySchema>;

const paginationSchema = {
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive().max(100),
  offset: z.number().int().nonnegative(),
};
const roomListSchema = z.object({ items: z.array(roomSchema), ...paginationSchema });
const versionSchema = z.object({
  commit_sha: z.string().min(1),
  environment: z.string().min(1),
  version: z.string().min(1),
});
const errorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), request_id: z.string().optional() }),
});

export const REQUEST_TIMEOUT_MS = 8_000;

client.setConfig({
  baseUrl: import.meta.env.VITE_API_BASE_URL || globalThis.location?.origin || 'http://localhost',
  fetch: (input, init) => globalThis.fetch(input, init),
});

export const createdBookingSchema = z.object({
  id: z.string().uuid(),
  owner_id: z.string().uuid(),
  room_id: z.string().uuid(),
  starts_at: z.string().datetime({ offset: true }),
  ends_at: z.string().datetime({ offset: true }),
  status: z.literal('active'),
  created_at: z.string().datetime({ offset: true }),
});
export type CreatedBooking = z.infer<typeof createdBookingSchema>;
export interface BookingSubmission {
  body: CreateBooking;
  ownerId: string;
  csrfToken: string;
  idempotencyKey: string;
}
const bookingClient = createClient({
  baseUrl: globalThis.location?.origin || 'http://localhost',
  credentials: 'same-origin',
  fetch: (input, init) => globalThis.fetch(input, init),
});

interface ApiResult {
  data?: unknown;
  error?: unknown;
  response?: Response;
}

async function readResult<T>(
  run: (signal: AbortSignal) => Promise<ApiResult>,
  schema: z.ZodType<T>,
  mutation = false,
  parentSignal?: AbortSignal,
): Promise<T> {
  let result: ApiResult;
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS);
  const signal = parentSignal ? AbortSignal.any([parentSignal, timeout.signal]) : timeout.signal;
  try {
    result = await run(signal);
  } catch {
    throw new ApiError(
      mutation
        ? 'The request outcome is uncertain. Retry the same booking attempt to confirm it.'
        : 'The service could not be reached. Try again.',
      { uncertain: mutation },
    );
  } finally {
    clearTimeout(timer);
  }
  if (result.error !== undefined || !result.response?.ok) {
    const parsed = errorSchema.safeParse(result.error);
    throw new ApiError(
      parsed.success ? parsed.data.error.message : 'The request could not be completed.',
      {
        status: result.response?.status,
        code: result.response?.ok
          ? 'INVALID_RESPONSE'
          : parsed.success
            ? parsed.data.error.code
            : 'SERVICE_ERROR',
        requestId: parsed.success ? parsed.data.error.request_id : undefined,
        uncertain:
          mutation &&
          !(parsed.success && parsed.data.error.code === 'FEATURE_NOT_AVAILABLE') &&
          (!result.response ||
            result.response.ok ||
            result.response.status >= 500 ||
            (parsed.success &&
              ['REQUEST_IN_PROGRESS', 'BOOKING_BUSY'].includes(parsed.data.error.code))),
      },
    );
  }
  const parsed = schema.safeParse(result.data);
  if (!parsed.success) {
    throw new ApiError('The service returned an unexpected response. Refresh before continuing.', {
      status: result.response.status,
      code: 'INVALID_RESPONSE',
      uncertain: mutation,
    });
  }
  return parsed.data;
}

export const api = {
  room: (
    roomId: string,
    query: { starts_at?: string; ends_at?: string } = {},
    signal?: AbortSignal,
  ) =>
    readResult(
      (requestSignal) =>
        getRoom({ path: { room_id: roomId }, query, signal: requestSignal, cache: 'no-store' }),
      roomSchema.refine(
        (room) => room.id === roomId && (!query.starts_at || typeof room.available === 'boolean'),
      ),
      false,
      signal,
    ),
  roomDay: (roomId: string, date: string, signal?: AbortSignal) =>
    readResult(
      (requestSignal) =>
        getRoomDayAvailability({
          path: { room_id: roomId },
          query: { date },
          signal: requestSignal,
          cache: 'no-store',
        }),
      roomDaySchema.refine((day) => day.room.id === roomId && day.date === date),
      false,
      signal,
    ),
  rooms: (
    query: Pagination & { starts_at?: string; ends_at?: string } = {},
    signal?: AbortSignal,
  ) =>
    readResult(
      (requestSignal) => listRooms({ query, signal: requestSignal }),
      query.starts_at && query.ends_at
        ? roomListSchema.refine((value) =>
            value.items.every((room) => typeof room.available === 'boolean'),
          )
        : roomListSchema,
      false,
      signal,
    ),
  bookings: (
    query: Pagination & { from: string; to: string; room_id?: string },
    signal?: AbortSignal,
  ) =>
    readResult(
      (requestSignal) => provisionalBookings.list(query, requestSignal),
      bookingListSchema,
      false,
      signal,
    ),
  createBooking: ({ body, ownerId, csrfToken, idempotencyKey }: BookingSubmission) =>
    readResult(
      (signal) =>
        createBooking({
          client: bookingClient,
          body,
          signal,
          cache: 'no-store',
          headers: { 'idempotency-key': idempotencyKey, 'X-CSRF-Token': csrfToken },
        }),
      createdBookingSchema.refine(
        (booking) =>
          booking.owner_id === ownerId &&
          booking.room_id === body.room_id &&
          Date.parse(booking.starts_at) === Date.parse(body.starts_at) &&
          Date.parse(booking.ends_at) === Date.parse(body.ends_at),
      ),
      true,
    ),
  cancelBooking: (id: string) =>
    readResult(
      (signal) => provisionalBookings.cancel(id, signal),
      bookingSchema.refine((booking) => booking.id === id && booking.status === 'cancelled'),
      true,
    ),
  version: (signal?: AbortSignal) =>
    readResult(
      (requestSignal) => getVersion({ signal: requestSignal }),
      versionSchema,
      false,
      signal,
    ),
};
