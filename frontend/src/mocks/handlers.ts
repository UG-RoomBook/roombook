import { http, HttpResponse } from 'msw';
import { z } from 'zod';
import type { Booking, Room } from '@/shared/api/types';
import { mockBookings, mockRooms } from './data';

function error(status: number, code: string, message: string) {
  return HttpResponse.json({ error: { code, message, request_id: 'mock-request' } }, { status });
}

const intervalSchema = z
  .object({
    starts_at: z.string().datetime({ offset: true }),
    ends_at: z.string().datetime({ offset: true }),
  })
  .refine((value) => Date.parse(value.starts_at) < Date.parse(value.ends_at));
const createSchema = intervalSchema.and(z.object({ room_id: z.string().uuid() }));

function pagination(url: URL) {
  const limit = Number(url.searchParams.get('limit') ?? 20);
  const offset = Number(url.searchParams.get('offset') ?? 0);
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 100 ||
    !Number.isInteger(offset) ||
    offset < 0
  )
    return null;
  return { limit, offset };
}

function overlap(booking: Booking, start: string, end: string) {
  return (
    Date.parse(booking.starts_at) < Date.parse(end) &&
    Date.parse(booking.ends_at) > Date.parse(start)
  );
}

export const handlers = [
  http.get('*/version', () =>
    HttpResponse.json({ commit_sha: 'mock-data', environment: 'development', version: '0.1.0' }),
  ),
  http.get('*/api/v1/rooms', ({ request }) => {
    const url = new URL(request.url);
    const page = pagination(url);
    if (!page) return error(422, 'VALIDATION_ERROR', 'Choose a valid page.');
    const start = url.searchParams.get('starts_at');
    const end = url.searchParams.get('ends_at');
    if ((start || end) && !intervalSchema.safeParse({ starts_at: start, ends_at: end }).success)
      return error(
        422,
        'VALIDATION_ERROR',
        'Choose a valid interval with explicit timezone offsets.',
      );
    const items: Room[] = mockRooms.map((room) => ({
      ...room,
      ...(start && end
        ? {
            available:
              room.active &&
              !mockBookings.some(
                (booking) =>
                  booking.room_id === room.id &&
                  booking.status === 'active' &&
                  overlap(booking, start, end),
              ),
          }
        : {}),
    }));
    return HttpResponse.json({
      items: items.slice(page.offset, page.offset + page.limit),
      total: items.length,
      ...page,
    });
  }),
  http.get('*/api/v1/bookings', ({ request }) => {
    const url = new URL(request.url);
    const page = pagination(url);
    const start = url.searchParams.get('from');
    const end = url.searchParams.get('to');
    if (!page || !intervalSchema.safeParse({ starts_at: start, ends_at: end }).success)
      return error(422, 'VALIDATION_ERROR', 'Choose a valid booking date range.');
    const room = url.searchParams.get('room_id');
    const items = mockBookings
      .filter((booking) => (!room || booking.room_id === room) && overlap(booking, start!, end!))
      .sort(
        (left, right) =>
          Date.parse(left.starts_at) - Date.parse(right.starts_at) ||
          left.id.localeCompare(right.id),
      );
    return HttpResponse.json({
      items: items.slice(page.offset, page.offset + page.limit),
      total: items.length,
      ...page,
    });
  }),
  http.post('*/api/v1/bookings', async ({ request }) => {
    const parsed = createSchema.safeParse(await request.json());
    if (!parsed.success) return error(422, 'VALIDATION_ERROR', 'Choose a valid room and interval.');
    const { room_id, starts_at, ends_at } = parsed.data;
    const room = mockRooms.find((item) => item.id === room_id);
    if (!room) return error(404, 'ROOM_NOT_FOUND', 'This room could not be found.');
    if (
      !room.active ||
      mockBookings.some(
        (booking) =>
          booking.room_id === room_id &&
          booking.status === 'active' &&
          overlap(booking, starts_at, ends_at),
      )
    )
      return error(
        409,
        'BOOKING_CONFLICT',
        'This room is no longer available for the selected time.',
      );
    const booking: Booking = {
      id: crypto.randomUUID(),
      room_id,
      starts_at,
      ends_at,
      status: 'active',
      created_at: new Date().toISOString(),
      cancelled_at: null,
    };
    mockBookings.push(booking);
    return HttpResponse.json(booking, { status: 201 });
  }),
  http.post('*/api/v1/bookings/:id/cancel', ({ params }) => {
    const booking = mockBookings.find((item) => item.id === params.id);
    if (!booking) return error(404, 'BOOKING_NOT_FOUND', 'This booking could not be found.');
    if (booking.status === 'active') {
      booking.status = 'cancelled';
      booking.cancelled_at = new Date().toISOString();
    }
    return HttpResponse.json(booking);
  }),
];
