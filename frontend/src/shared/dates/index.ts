import { Temporal } from '@js-temporal/polyfill';

export const CAMPUS_TIME_ZONE = 'Australia/Melbourne';

export type CampusIntervalInput = { date: string; start: string; end: string };
export type CampusInterval = { starts_at: string; ends_at: string };

function parseDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new RangeError('Choose a valid date.');
  }
  try {
    return Temporal.PlainDate.from(value, { overflow: 'reject' });
  } catch {
    throw new RangeError('Choose a valid date.');
  }
}

function campusDateTime(date: Temporal.PlainDate, time: string) {
  if (!/^\d{2}:\d{2}$/.test(time)) {
    throw new RangeError('Choose a valid start and end time.');
  }
  let plainTime: Temporal.PlainTime;
  try {
    plainTime = Temporal.PlainTime.from(time, { overflow: 'reject' });
  } catch {
    throw new RangeError('Choose a valid start and end time.');
  }
  try {
    return Temporal.ZonedDateTime.from(
      {
        timeZone: CAMPUS_TIME_ZONE,
        year: date.year,
        month: date.month,
        day: date.day,
        hour: plainTime.hour,
        minute: plainTime.minute,
      },
      { disambiguation: 'reject', overflow: 'reject' },
    );
  } catch {
    throw new RangeError(
      'This time is skipped or repeated by Melbourne daylight saving. Choose another time.',
    );
  }
}

function offsetTimestamp(value: Temporal.ZonedDateTime) {
  return value.toString({ smallestUnit: 'second', timeZoneName: 'never' });
}

/** Return the calendar date at the campus, independent of the viewer's timezone. */
export function campusToday(now = Temporal.Now.instant().toString()): string {
  return Temporal.Instant.from(now).toZonedDateTimeISO(CAMPUS_TIME_ZONE).toPlainDate().toString();
}

/** Reject ambiguous/nonexistent wall-clock times instead of silently shifting a booking. */
export function toCampusInterval({ date, start, end }: CampusIntervalInput): CampusInterval {
  const day = parseDate(date);
  const startsAt = campusDateTime(day, start);
  const endsAt = campusDateTime(day, end);
  if (Temporal.ZonedDateTime.compare(startsAt, endsAt) >= 0) {
    throw new RangeError('Choose an end time after the start time.');
  }
  return { starts_at: offsetTimestamp(startsAt), ends_at: offsetTimestamp(endsAt) };
}

const MIN_BOOKING_MINUTES = 30;
const MAX_BOOKING_MINUTES = 120;

function bookingStart(date: string, start: string) {
  const value = campusDateTime(parseDate(date), start);
  if (value.minute % 15 !== 0) {
    throw new RangeError('Choose a start time on a 15-minute boundary.');
  }
  return value;
}

/** Selection rules only; the server still checks its clock, horizon and room calendar. */
export function toBookingInterval(input: CampusIntervalInput): CampusInterval {
  bookingStart(input.date, input.start);
  const interval = toCampusInterval(input);
  const minutes = (Date.parse(interval.ends_at) - Date.parse(interval.starts_at)) / 60_000;
  if (minutes < MIN_BOOKING_MINUTES || minutes > MAX_BOOKING_MINUTES) {
    throw new RangeError('Choose a duration from 30 minutes to 2 hours.');
  }
  return interval;
}

/** Keep minute precision and use elapsed time, including across Melbourne DST changes. */
export function bookingEndTimes(date: string, start: string): { times: string[]; error: string } {
  try {
    const begins = bookingStart(date, start);
    const day = begins.toPlainDate();
    const times: string[] = [];
    for (let minutes = MIN_BOOKING_MINUTES; minutes <= MAX_BOOKING_MINUTES; minutes++) {
      const end = begins.add({ minutes });
      if (!end.toPlainDate().equals(day)) continue;
      const time = end.toPlainTime().toString({ smallestUnit: 'minute' });
      try {
        // A repeated endpoint is invalid even when elapsed arithmetic picked an offset.
        campusDateTime(day, time);
        times.push(time);
      } catch {
        continue;
      }
    }
    return { times, error: '' };
  } catch (error) {
    return { times: [], error: error instanceof Error ? error.message : 'Choose a valid start.' };
  }
}

/** Melbourne calendar boundaries cover 23, 24 or 25 hours as appropriate. */
export function campusDayRange(date: string): CampusInterval {
  const day = parseDate(date);
  const start = campusDateTime(day, '00:00');
  const end = campusDateTime(day.add({ days: 1 }), '00:00');
  return { starts_at: offsetTimestamp(start), ends_at: offsetTimestamp(end) };
}

export function formatCampusDate(value: string): string {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? parseDate(value)
    : Temporal.Instant.from(value).toZonedDateTimeISO(CAMPUS_TIME_ZONE).toPlainDate();
  // A date-only value has no timezone. Format at UTC noon so host settings cannot shift it.
  return new Intl.DateTimeFormat('en-AU', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(`${date.toString()}T12:00:00Z`));
}

export function formatCampusTime(value: string): string {
  return new Intl.DateTimeFormat('en-AU', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: CAMPUS_TIME_ZONE,
  }).format(new Date(Temporal.Instant.from(value).epochMilliseconds));
}
