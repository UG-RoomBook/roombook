import { z } from 'zod';
import { client } from './generated/client.gen';
import { getVersion, listRooms } from './generated/sdk.gen';
import { bookingListSchema, bookingSchema, provisionalBookings } from './provisional-bookings';
import type { CreateBooking, Pagination } from './types';

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
        ? 'The request outcome is uncertain. Refresh bookings before trying again.'
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
          (!result.response || result.response.ok || result.response.status >= 500),
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
  createBooking: (body: CreateBooking) =>
    readResult(
      (signal) => provisionalBookings.create(body, signal),
      bookingSchema.refine(
        (booking) =>
          booking.room_id === body.room_id &&
          booking.status === 'active' &&
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
