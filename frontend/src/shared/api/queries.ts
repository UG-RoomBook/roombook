import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { campusDayRange, toCampusInterval } from '@/shared/dates';
import { api, ApiError } from './client';
import type { Pagination, Room, SearchFilters } from './types';

export const queryKeys = {
  rooms: ['rooms'] as const,
  catalog: ['room-catalog'] as const,
  bookings: ['bookings'] as const,
};

function retryRead(failureCount: number, error: Error) {
  return (
    failureCount < 1 &&
    error instanceof ApiError &&
    (error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504) &&
    error.code !== 'INVALID_RESPONSE'
  );
}

export function useRooms(filters: SearchFilters, enabled = true, pagination: Pagination = {}) {
  return useQuery({
    queryKey: [...queryKeys.rooms, filters, pagination],
    queryFn: ({ signal }) =>
      api.rooms(
        {
          ...(filters.start && filters.end ? toCampusInterval(filters) : {}),
          limit: pagination.limit ?? 20,
          offset: pagination.offset ?? 0,
        },
        signal,
      ),
    enabled,
    staleTime: filters.start && filters.end ? 0 : 60_000,
    retry: retryRead,
  });
}

export const MAX_CATALOG_PAGES = 20;

export async function fetchRoomCatalog(
  signal?: AbortSignal,
  interval: { starts_at?: string; ends_at?: string } = {},
): Promise<Room[]> {
  const rooms: Room[] = [];
  let offset = 0;
  for (let page = 0; page < MAX_CATALOG_PAGES; page += 1) {
    const result = await api.rooms({ ...interval, limit: 100, offset }, signal);
    rooms.push(...result.items);
    if (offset + result.items.length >= result.total) return rooms;
    if (result.items.length === 0) break;
    offset += result.items.length;
  }
  throw new ApiError('Room details could not be fully loaded. Return to search and try again.', {
    code: 'ROOM_LOOKUP_LIMIT',
  });
}

export function useRoomCatalog() {
  return useQuery({
    queryKey: queryKeys.catalog,
    queryFn: ({ signal }) => fetchRoomCatalog(signal),
    staleTime: 60_000,
    retry: retryRead,
  });
}

export function useRoom(roomId: string, filters: SearchFilters, enabled = true) {
  return useQuery({
    queryKey: [...queryKeys.rooms, 'detail', roomId, filters],
    queryFn: async ({ signal }) => {
      const rooms = await fetchRoomCatalog(signal, toCampusInterval(filters));
      const room = rooms.find((item) => item.id === roomId);
      if (!room)
        throw new ApiError('This room could not be found. Return to search.', {
          status: 404,
          code: 'ROOM_NOT_FOUND',
        });
      return room;
    },
    enabled,
    retry: retryRead,
    staleTime: 0,
  });
}

export function useBookingList(date: string, roomId?: string, pagination: Pagination = {}) {
  return useQuery({
    queryKey: [...queryKeys.bookings, date, roomId, pagination],
    queryFn: ({ signal }) => {
      const range = campusDayRange(date);
      return api.bookings(
        {
          from: range.starts_at,
          to: range.ends_at,
          room_id: roomId,
          limit: pagination.limit ?? 20,
          offset: pagination.offset ?? 0,
        },
        signal,
      );
    },
    retry: retryRead,
    staleTime: 0,
  });
}

export function useCancelBooking() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ['bookings', 'cancel'],
    mutationFn: api.cancelBooking,
    retry: false,
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.rooms }),
        client.invalidateQueries({ queryKey: queryKeys.bookings }),
      ]),
  });
}

export function useRuntimeVersion() {
  return useQuery({
    queryKey: ['runtime-version'],
    queryFn: ({ signal }) => api.version(signal),
    staleTime: 60_000,
    retry: retryRead,
  });
}
