import { describe, expect, it } from 'vitest';
import { bookingDateSchema, readBookingSelection, readOffset, searchPath } from './selection';

describe('booking route selection', () => {
  it.each([
    ['13:00', '13:29'],
    ['13:00', '15:01'],
    ['13:01', '14:00'],
  ])('rejects an invalid direct review URL: %s–%s', (start, end) => {
    const params = new URLSearchParams({ room_id: 'studio', date: '2026-10-23', start, end });
    expect(readBookingSelection(params).selection).toBeNull();
  });

  it.each(['13:30', '15:00'])('accepts the duration boundary in a review URL: %s', (end) => {
    const params = new URLSearchParams({
      room_id: 'studio',
      date: '2026-10-23',
      start: '13:00',
      end,
    });
    expect(readBookingSelection(params).selection?.end).toBe(end);
  });

  it('requires a room and positive group size', () => {
    expect(readBookingSelection(new URLSearchParams()).selection).toBeNull();
    expect(
      readBookingSelection(
        new URLSearchParams('room_id=studio&date=2026-10-19&start=13:00&end=14:00&capacity=0'),
      ).selection,
    ).toBeNull();
  });

  it('rejects dates that do not exist and repeated Melbourne wall-clock times', () => {
    expect(
      readBookingSelection(
        new URLSearchParams('room_id=studio&date=2026-02-30&start=13:00&end=14:00'),
      ).error,
    ).toBe('Choose a valid date.');
    expect(
      readBookingSelection(
        new URLSearchParams('room_id=studio&date=2027-04-04&start=02:00&end=03:00'),
      ).error,
    ).toMatch(/daylight saving/);
    expect(bookingDateSchema.safeParse({ date: '2026-02-30' }).success).toBe(false);
  });

  it('keeps filters and result position when returning to search', () => {
    const params = new URLSearchParams(
      'room_id=studio&date=2026-10-19&start=13:00&end=14:00&capacity=4&offset=20&outcome=unknown',
    );
    expect(searchPath(params)).toBe(
      '/?date=2026-10-19&start=13%3A00&end=14%3A00&capacity=4&offset=20',
    );
    expect(searchPath(new URLSearchParams())).toBe('/');
    expect(readBookingSelection(params).selection?.capacity).toBe(4);
  });

  it('bounds list offsets to nonnegative safe integers', () => {
    expect(readOffset(new URLSearchParams('offset=20'))).toBe(20);
    for (const value of ['-1', 'abc', '1.5', '9007199254740992']) {
      expect(readOffset(new URLSearchParams({ offset: value }))).toBe(0);
    }
  });
});
