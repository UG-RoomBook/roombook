import { describe, expect, it } from 'vitest';
import { bookingEndTimes, toBookingInterval, toCampusInterval } from './index';

describe('booking selection policy', () => {
  it.each(['13:30', '13:31', '15:00'])('allows the valid end %s', (end) => {
    expect(toBookingInterval({ date: '2026-10-23', start: '13:00', end }).ends_at).toContain(end);
  });

  it.each(['13:29', '15:01', '16:00'])('rejects out-of-range end %s', (end) => {
    expect(() => toBookingInterval({ date: '2026-10-23', start: '13:00', end })).toThrow(
      '30 minutes to 2 hours',
    );
  });

  it('requires a quarter-hour start without rounding the selection', () => {
    expect(() => toBookingInterval({ date: '2026-10-23', start: '13:01', end: '14:00' })).toThrow(
      '15-minute boundary',
    );
    expect(bookingEndTimes('2026-10-23', '13:01').times).toEqual([]);
  });

  it('keeps all valid end minutes, including both duration boundaries', () => {
    const { times } = bookingEndTimes('2026-10-23', '13:00');
    expect(times).toHaveLength(91);
    expect(times[0]).toBe('13:30');
    expect(times.at(-1)).toBe('15:00');
    expect(times).toContain('14:01');
    expect(times).not.toContain('13:29');
    expect(times).not.toContain('15:01');
  });

  it('never rolls a late-night end into the next day', () => {
    expect(bookingEndTimes('2026-10-23', '23:15').times).toEqual(
      Array.from({ length: 15 }, (_, i) => `23:${45 + i}`),
    );
    expect(bookingEndTimes('2026-10-23', '23:30').times).toEqual([]);
    expect(() => toBookingInterval({ date: '2026-10-23', start: '23:00', end: '00:00' })).toThrow(
      'after the start',
    );
  });

  it('uses elapsed durations across the spring DST gap', () => {
    const { times } = bookingEndTimes('2026-10-04', '01:30');
    expect(times[0]).toBe('03:00');
    expect(times.at(-1)).toBe('04:30');
    expect(times.some((time) => time.startsWith('02:'))).toBe(false);
    expect(toBookingInterval({ date: '2026-10-04', start: '01:30', end: '04:30' })).toEqual({
      starts_at: '2026-10-04T01:30:00+10:00',
      ends_at: '2026-10-04T04:30:00+11:00',
    });
  });

  it('rejects repeated endpoints and excessive elapsed duration in autumn', () => {
    const { times } = bookingEndTimes('2026-04-05', '01:00');
    expect(times[0]).toBe('01:30');
    expect(times.at(-1)).toBe('01:59');
    expect(() => toBookingInterval({ date: '2026-04-05', start: '01:00', end: '03:00' })).toThrow(
      '30 minutes to 2 hours',
    );
    expect(() => toBookingInterval({ date: '2026-04-05', start: '01:00', end: '02:00' })).toThrow(
      'daylight saving',
    );
  });

  it.each([
    ['2026-10-04', '02:00', 'daylight saving'],
    ['2026-04-05', '02:00', 'daylight saving'],
    ['2026-02-30', '13:00', 'valid date'],
    ['', '13:00', 'valid date'],
    ['2026-10-23', '', 'valid start'],
  ])('disables the picker for invalid date/start %s %s', (date, start, error) => {
    expect(bookingEndTimes(date, start)).toEqual({
      times: [],
      error: expect.stringContaining(error),
    });
  });

  it('does not apply booking constraints to generic historical intervals', () => {
    expect(toCampusInterval({ date: '2020-01-01', start: '13:01', end: '16:00' })).toEqual({
      starts_at: '2020-01-01T13:01:00+11:00',
      ends_at: '2020-01-01T16:00:00+11:00',
    });
  });
});
