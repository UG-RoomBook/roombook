import type { Booking, Room } from '@/shared/api/types';

export const mockRooms: Room[] = [
  {
    id: '10000000-0000-4000-8000-000000000001',
    name: 'The Studio',
    location: 'West building · Level 1',
    capacity: 4,
    active: true,
  },
  {
    id: '10000000-0000-4000-8000-000000000002',
    name: 'The Forum',
    location: 'North building · Level 2',
    capacity: 8,
    active: true,
  },
];

const initialBookings: Booking[] = [
  {
    id: '20000000-0000-4000-8000-000000000001',
    room_id: mockRooms[0]!.id,
    starts_at: '2026-10-19T10:00:00+11:00',
    ends_at: '2026-10-19T11:00:00+11:00',
    status: 'active',
    created_at: '2026-10-18T00:00:00Z',
    cancelled_at: null,
  },
  {
    id: '20000000-0000-4000-8000-000000000002',
    room_id: mockRooms[1]!.id,
    starts_at: '2026-10-19T15:00:00+11:00',
    ends_at: '2026-10-19T16:00:00+11:00',
    status: 'active',
    created_at: '2026-10-18T00:00:00Z',
    cancelled_at: null,
  },
];

export const mockBookings: Booking[] = structuredClone(initialBookings);

export function resetMockData() {
  mockBookings.splice(0, mockBookings.length, ...structuredClone(initialBookings));
}
