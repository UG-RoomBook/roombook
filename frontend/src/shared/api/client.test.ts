import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { handlers } from '@/mocks/handlers';
import { mockRooms, resetMockData } from '@/mocks/data';
import { api, ApiError, REQUEST_TIMEOUT_MS } from './client';
import { fetchRoomCatalog } from './queries';

const server = setupServer(...handlers);
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  resetMockData();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

const input = {
  room_id: mockRooms[0]!.id,
  starts_at: '2026-10-19T13:00:00+11:00',
  ends_at: '2026-10-19T14:00:00+11:00',
};

describe('API boundary', () => {
  it('uses the generated room operation and validates its response', async () => {
    const rooms = await api.rooms({ starts_at: input.starts_at, ends_at: input.ends_at });
    expect(rooms.items).toHaveLength(2);
    expect(rooms.items[0]).toMatchObject({ name: 'The Studio', available: true });
  });

  it('preserves an explicit-offset booking interval and observes cancellation', async () => {
    const booking = await api.createBooking(input);
    expect(booking).toMatchObject({ ...input, status: 'active' });
    const cancelled = await api.cancelBooking(booking.id);
    expect(cancelled.status).toBe('cancelled');
    expect((await api.cancelBooking(booking.id)).id).toBe(booking.id);
    const list = await api.bookings({
      from: '2026-10-19T00:00:00+11:00',
      to: '2026-10-20T00:00:00+11:00',
    });
    expect(list.items.find((item) => item.id === booking.id)?.status).toBe('cancelled');
  });

  it('retains status, code and request correlation on a conflict', async () => {
    await api.createBooking(input);
    await expect(api.createBooking(input)).rejects.toMatchObject({
      status: 409,
      code: 'BOOKING_CONFLICT',
      requestId: 'mock-request',
      uncertain: false,
    });
  });

  it('rejects malformed successful responses instead of trusting generated types', async () => {
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({ items: [{ id: 'invalid' }], total: 1, limit: 20, offset: 0 }),
      ),
    );
    await expect(api.rooms()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });

  it('treats an invalid create response as an uncertain outcome', async () => {
    server.use(http.post('*/api/v1/bookings', () => HttpResponse.json({}, { status: 201 })));
    await expect(api.createBooking(input)).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
      uncertain: true,
    });
  });

  it('treats a failed mutation connection as uncertain', async () => {
    server.use(http.post('*/api/v1/bookings', () => HttpResponse.error()));
    await expect(api.createBooking(input)).rejects.toMatchObject({ status: 0, uncertain: true });
  });

  it('keeps a successful create with unreadable JSON uncertain', async () => {
    server.use(
      http.post(
        '*/api/v1/bookings',
        () =>
          new HttpResponse('{"id":', {
            status: 201,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    );
    await expect(api.createBooking(input)).rejects.toMatchObject({
      status: 201,
      code: 'INVALID_RESPONSE',
      uncertain: true,
    });
  });

  it('bounds a stalled request and does not repeat its mutation', async () => {
    vi.useFakeTimers();
    let calls = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (request) =>
        new Promise((_, reject) => {
          calls += 1;
          (request as Request).signal.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          );
        }),
    );
    const outcome = api.createBooking(input).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    expect(await outcome).toBeInstanceOf(ApiError);
    expect(await outcome).toMatchObject({ uncertain: true });
    expect(calls).toBe(1);
  });

  it('loads subsequent catalog pages without N+1 calls for booking rows', async () => {
    const requests: number[] = [];
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        requests.push(offset);
        return HttpResponse.json({ items: [mockRooms[offset]], total: 2, limit: 1, offset });
      }),
    );
    expect(await fetchRoomCatalog()).toHaveLength(2);
    expect(requests).toEqual([0, 1]);
  });

  it('fails explicitly when catalog pagination makes no progress', async () => {
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({ items: [], total: 100, limit: 100, offset: 0 }),
      ),
    );
    await expect(fetchRoomCatalog()).rejects.toMatchObject({ code: 'ROOM_LOOKUP_LIMIT' });
  });
});
