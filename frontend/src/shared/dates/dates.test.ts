import { describe, expect, it } from 'vitest';
import {
  campusDayRange,
  campusToday,
  formatCampusDate,
  formatCampusTime,
  toCampusInterval,
} from './index';

describe('Melbourne campus dates', () => {
  it('uses the campus date when UTC is still on the previous day', () => {
    expect(campusToday('2026-10-18T14:30:00Z')).toBe('2026-10-19');
  });

  it.each([
    ['2026-06-01', '+10:00'],
    ['2026-10-19', '+11:00'],
  ])('sends explicit campus offsets on %s', (date, offset) => {
    expect(toCampusInterval({ date, start: '13:00', end: '14:00' })).toEqual({
      starts_at: `${date}T13:00:00${offset}`,
      ends_at: `${date}T14:00:00${offset}`,
    });
  });

  it.each([
    ['2026-10-04', '02:30', '03:30'],
    ['2026-04-05', '02:30', '03:30'],
  ])('rejects skipped or repeated times on %s', (date, start, end) => {
    expect(() => toCampusInterval({ date, start, end })).toThrow('daylight saving');
  });

  it.each([
    ['2026-10-04', 23],
    ['2026-04-05', 25],
    ['2026-10-19', 24],
  ])('covers the complete %s calendar day (%i hours)', (date, hours) => {
    const { starts_at, ends_at } = campusDayRange(date);
    expect((Date.parse(ends_at) - Date.parse(starts_at)) / 3_600_000).toBe(hours);
  });

  it.each([
    { date: '2026-02-30', start: '13:00', end: '14:00' },
    { date: '2026-10-19', start: '25:00', end: '26:00' },
    { date: '2026-10-19', start: '14:00', end: '13:00' },
    { date: '2026-10-19', start: '13:00', end: '13:00' },
    { date: '', start: '13:00', end: '14:00' },
  ])('rejects invalid or non-positive intervals: $date $start–$end', (interval) => {
    expect(() => toCampusInterval(interval)).toThrow(RangeError);
  });

  it('does not introduce a past-date restriction', () => {
    expect(toCampusInterval({ date: '2020-01-01', start: '13:00', end: '14:00' }).starts_at).toBe(
      '2020-01-01T13:00:00+11:00',
    );
  });

  it('formats date-only values and instants consistently in Melbourne', () => {
    expect(formatCampusDate('2026-10-19')).toBe('Mon, 19 Oct');
    expect(formatCampusDate('2026-10-18T14:30:00Z')).toBe('Mon, 19 Oct');
    expect(formatCampusTime('2026-10-19T02:00:00Z')).toBe('13:00');
  });

  it('rejects malformed calendar-day filters', () => {
    expect(() => campusDayRange('2026-2-1')).toThrow('valid date');
  });
});
