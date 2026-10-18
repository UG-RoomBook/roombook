import type { RoomRead } from './generated/types.gen';

export type { RoomList, RuntimeVersion } from './generated/types.gen';
export type { Booking, BookingList, CreateBooking } from './provisional-bookings';

// The API omits availability when no interval is requested.
export type Room = RoomRead & { available?: boolean };

export interface SearchFilters {
  date: string;
  start: string;
  end: string;
  capacity: number;
}

export interface Pagination {
  limit?: number;
  offset?: number;
}
