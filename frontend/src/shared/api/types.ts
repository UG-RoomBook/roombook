export type {
  Room,
  RoomList,
  Booking,
  BookingList,
  CreateBooking,
  RuntimeVersion,
} from './generated/types.gen';

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
