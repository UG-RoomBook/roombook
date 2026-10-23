import { z } from 'zod';
import * as sdk from '@/shared/api/generated/sdk.gen';
import type {
  AdminBookingsData,
  AdminActivityData,
  RoomCreate,
  RoomUpdate,
  ScheduleUpdate,
  UserUpdate,
} from '@/shared/api/generated/types.gen';
import { accountClient as client, run } from '@/features/accounts/api';

export const roomSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  location: z.string(),
  capacity: z.number(),
  active: z.boolean(),
  hours_confirmed: z.boolean(),
  revision: z.number(),
});
export const userSchema = z.object({
  id: z.uuid(),
  verified_email: z.string().nullable(),
  email_checked_at: z.string().nullable(),
  role: z.enum(['Member', 'Admin']),
  is_active: z.boolean(),
  revision: z.number(),
  created_at: z.string(),
});
export const bookingSchema = z.object({
  id: z.uuid(),
  room_id: z.uuid(),
  room_name: z.string(),
  owner_id: z.uuid().nullable(),
  owner_label: z.string(),
  starts_at: z.string(),
  ends_at: z.string(),
  created_at: z.string(),
  cancelled_at: z.string().nullable(),
  status: z.enum(['Upcoming', 'Ongoing', 'Completed', 'Cancelled']),
});
export const activitySchema = z.object({
  id: z.uuid(),
  actor_user_id: z.uuid().nullable(),
  actor_label: z.string(),
  target_id: z.uuid().nullable(),
  action: z.string(),
  occurred_at: z.string(),
  details: z.record(z.string(), z.unknown()),
});
const hours = z.object({ start_minute: z.number(), end_minute: z.number() });
export const scheduleSchema = z.object({
  room_id: z.uuid(),
  revision: z.number(),
  timezone: z.literal('Australia/Melbourne'),
  hours_confirmed: z.boolean(),
  weekly: z.array(hours.extend({ weekday: z.number() })),
  exceptions: z.array(z.object({ date: z.string(), windows: z.array(hours) })),
  closures: z.array(z.object({ starts_at: z.string(), ends_at: z.string(), reason: z.string() })),
});
const page = <T>(item: z.ZodType<T>) =>
  z.object({ items: z.array(item), total: z.number(), offset: z.number(), limit: z.number() });
const impactSchema = z.object({
  revision: z.number(),
  affected_count: z.number(),
  affected_bookings: z.array(bookingSchema),
  generated_at: z.string(),
});
const overviewSchema = z.object({
  generated_at: z.string(),
  timezone: z.literal('Australia/Melbourne'),
  active_rooms: z.number(),
  active_users: z.number(),
  bookings_today: z.number(),
  unconfirmed_rooms: z.number(),
  agenda: z.array(bookingSchema),
  recent_activity: z.array(activitySchema),
});
export type Room = z.infer<typeof roomSchema>;
export type User = z.infer<typeof userSchema>;
export type Booking = z.infer<typeof bookingSchema>;
export type Schedule = z.infer<typeof scheduleSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type Impact = z.infer<typeof impactSchema>;
export type Paging = { limit: number; offset: number; search?: string };
const headers = (csrf: string, key: string) => ({ 'X-CSRF-Token': csrf, 'Idempotency-Key': key });
export const adminApi = {
  overview: (parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminOverview({ client, signal, cache: 'no-store' }),
      overviewSchema,
      parent,
    ),
  rooms: (query: Paging, parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminRooms({ client, query, signal, cache: 'no-store' }),
      page(roomSchema),
      parent,
    ),
  room: (id: string, parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminRoom({ client, path: { room_id: id }, signal, cache: 'no-store' }),
      roomSchema,
      parent,
    ),
  createRoom: (body: RoomCreate, csrf: string, key: string) =>
    run(
      (signal) => sdk.adminCreateRoom({ client, signal, body, headers: headers(csrf, key) }),
      roomSchema,
    ),
  updateRoom: (id: string, body: RoomUpdate, csrf: string, key: string) =>
    run(
      (signal) =>
        sdk.adminUpdateRoom({
          client,
          signal,
          path: { room_id: id },
          body,
          headers: headers(csrf, key),
        }),
      roomSchema,
    ),
  schedule: (id: string, parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminSchedule({ client, signal, path: { room_id: id }, cache: 'no-store' }),
      scheduleSchema,
      parent,
    ),
  updateSchedule: (id: string, body: ScheduleUpdate, csrf: string, key: string) =>
    run(
      (signal) =>
        sdk.adminUpdateSchedule({
          client,
          signal,
          path: { room_id: id },
          body,
          headers: headers(csrf, key),
        }),
      scheduleSchema,
    ),
  impact: (id: string, body: RoomUpdate | ScheduleUpdate, csrf: string) =>
    run(
      (signal) =>
        sdk.adminRoomImpact({
          client,
          signal,
          path: { room_id: id },
          body,
          headers: { 'X-CSRF-Token': csrf },
        }),
      impactSchema,
    ),
  bookings: (query: AdminBookingsData['query'], parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminBookings({ client, query, signal, cache: 'no-store' }),
      page(bookingSchema).extend({ generated_at: z.string() }),
      parent,
    ),
  booking: (id: string, parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminBooking({ client, path: { booking_id: id }, signal, cache: 'no-store' }),
      bookingSchema,
      parent,
    ),
  cancel: (id: string, reason: string, csrf: string, key: string) =>
    run(
      (signal) =>
        sdk.adminCancelBooking({
          client,
          signal,
          path: { booking_id: id },
          body: { reason },
          headers: headers(csrf, key),
        }),
      bookingSchema,
    ),
  users: (query: Paging, parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminUsers({ client, query, signal, cache: 'no-store' }),
      page(userSchema),
      parent,
    ),
  user: (id: string, parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminUser({ client, path: { user_id: id }, signal, cache: 'no-store' }),
      userSchema,
      parent,
    ),
  updateUser: (id: string, body: UserUpdate, csrf: string, key: string) =>
    run(
      (signal) =>
        sdk.adminUpdateUser({
          client,
          signal,
          path: { user_id: id },
          body,
          headers: headers(csrf, key),
        }),
      userSchema,
    ),
  activity: (query: AdminActivityData['query'], parent?: AbortSignal) =>
    run(
      (signal) => sdk.adminActivity({ client, query, signal, cache: 'no-store' }),
      page(activitySchema),
      parent,
    ),
};
