// Demo-only schedule. Production choices always come from the shared backend policy.
import { Temporal } from '@js-temporal/polyfill';
import type { RoomDay } from '@/shared/api/client';
import type { Room } from '@/shared/api/types';
import { toBookingInterval } from '@/shared/dates';
import { mockBookings } from './data';

export function demoRoomDay(room: Room, date: string): RoomDay {
  const now = Temporal.Now.instant();
  return {
    room,
    date,
    timezone: 'Australia/Melbourne',
    generated_at: now.toString(),
    booking_window_ends_at: now.add({ hours: 14 * 24 }).toString(),
    slots: Array.from({ length: 96 }, (_, i) => {
      const time =
        `${Math.floor(i / 4)}`.padStart(2, '0') + ':' + `${(i % 4) * 15}`.padStart(2, '0');
      const valid_ends: RoomDay['slots'][number]['valid_ends'] = [];
      let starts_at: string | null = null;
      for (let length = 30; length <= 120; length += 15) {
        const minute = i * 15 + length;
        if (i < 36 || minute > 17 * 60) continue;
        const end =
          `${Math.floor(minute / 60)}`.padStart(2, '0') + ':' + `${minute % 60}`.padStart(2, '0');
        try {
          const interval = toBookingInterval({ date, start: time, end });
          starts_at = interval.starts_at;
          if (
            room.active &&
            Date.parse(starts_at) > now.epochMilliseconds &&
            Date.parse(starts_at) <= now.add({ hours: 14 * 24 }).epochMilliseconds &&
            !mockBookings.some(
              (booking) =>
                booking.room_id === room.id &&
                booking.status === 'active' &&
                Date.parse(booking.starts_at) < Date.parse(interval.ends_at) &&
                Date.parse(booking.ends_at) > Date.parse(starts_at!),
            )
          )
            valid_ends.push({ time: end, ends_at: interval.ends_at });
        } catch {
          /* DST endpoint or invalid demo date: unavailable. */
        }
      }
      return {
        time,
        starts_at,
        available: valid_ends.length > 0,
        unavailable_reason: valid_ends.length ? null : room.active ? 'unavailable' : 'inactive',
        valid_ends,
      };
    }),
  };
}
