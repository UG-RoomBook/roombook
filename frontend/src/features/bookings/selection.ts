import { z } from 'zod';
import { campusDayRange, toCampusInterval } from '@/shared/dates';
import type { SearchFilters } from '@/shared/api/types';

const selectionSchema = z.object({
  roomId: z.string().trim().min(1),
  date: z.string(),
  start: z.string(),
  end: z.string(),
  capacity: z.number().int().positive(),
});

export type BookingSelection = SearchFilters & { roomId: string };

export function readBookingSelection(
  params: URLSearchParams,
): { selection: BookingSelection; error: null } | { selection: null; error: string } {
  const parsed = selectionSchema.safeParse({
    roomId: params.get('room_id') ?? '',
    date: params.get('date') ?? '',
    start: params.get('start') ?? '',
    end: params.get('end') ?? '',
    capacity: Number(params.get('capacity') ?? '1'),
  });
  if (!parsed.success) {
    return { selection: null, error: 'Choose a room, date, time and group size before booking.' };
  }
  try {
    toCampusInterval(parsed.data);
    return { selection: parsed.data, error: null };
  } catch (error) {
    return {
      selection: null,
      error: error instanceof Error ? error.message : 'Choose a valid date and time.',
    };
  }
}

export function searchPath(params: URLSearchParams): string {
  const filters = new URLSearchParams();
  for (const key of ['date', 'start', 'end', 'capacity', 'offset']) {
    const value = params.get(key);
    if (value !== null) filters.set(key, value);
  }
  const query = filters.toString();
  return query ? `/?${query}` : '/';
}

export const bookingDateSchema = z.object({
  date: z.string().refine((value) => {
    try {
      campusDayRange(value);
      return true;
    } catch {
      return false;
    }
  }, 'Choose a valid date.'),
});

export type BookingDateValues = z.infer<typeof bookingDateSchema>;

export function readOffset(params: URLSearchParams): number {
  const offset = Number(params.get('offset') ?? '0');
  return Number.isSafeInteger(offset) && offset >= 0 ? offset : 0;
}
