import { useEffect, useId, useMemo } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Search } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { z } from 'zod';
import { useRooms } from '@/shared/api/queries';
import { ApiError } from '@/shared/api/client';
import type { Room, SearchFilters } from '@/shared/api/types';
import { bookingEndTimes, campusToday, formatCampusDate, toBookingInterval } from '@/shared/dates';
import { Button, PageTitle, StateMessage } from '@/shared/ui';
import { RoomCard } from './RoomCard';
import './rooms.css';

const PAGE_SIZE = 20;
const CAPACITIES = [1, 4, 6, 8];
const END_TIMES = Array.from(
  { length: 24 * 60 },
  (_, minute) =>
    `${Math.floor(minute / 60)}`.padStart(2, '0') + ':' + `${minute % 60}`.padStart(2, '0'),
);

const searchSchema = z
  .object({
    date: z.string().min(1, 'Choose a date.'),
    start: z.string().min(1, 'Choose a start time.'),
    end: z.string().min(1, 'Choose an end time.'),
    capacity: z.number().int().positive('Choose a valid group size.'),
  })
  .superRefine((value, context) => {
    if (!value.date || !value.start || !value.end) return;
    try {
      toBookingInterval(value);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Choose a valid interval.';
      context.addIssue({
        code: 'custom',
        path: [message.includes('date') ? 'date' : message.includes('boundary') ? 'start' : 'end'],
        message,
      });
    }
  });

function filtersFromUrl(params: URLSearchParams): SearchFilters {
  const capacity = Number(params.get('capacity') ?? 1);
  return {
    date: params.get('date') ?? campusToday(),
    start: params.get('start') ?? '',
    end: params.get('end') ?? '',
    capacity: Number.isSafeInteger(capacity) && capacity > 0 ? capacity : 1,
  };
}

function intervalState(filters: SearchFilters) {
  if (!filters.start && !filters.end) return { hasInterval: false, error: '' };
  try {
    toBookingInterval(filters);
    return { hasInterval: true, error: '' };
  } catch (error) {
    return {
      hasInterval: false,
      error: error instanceof Error ? error.message : 'Choose a valid interval.',
    };
  }
}

function pageOffset(params: URLSearchParams) {
  const offset = Number(params.get('offset') ?? 0);
  return Number.isSafeInteger(offset) && offset >= 0 ? offset : 0;
}

export function FindRoomPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const formId = useId();
  const urlState = searchParams.toString();
  const applied = filtersFromUrl(searchParams);
  const offset = pageOffset(searchParams);
  const interval = intervalState(applied);
  const rooms = useRooms(applied, !interval.error, { limit: PAGE_SIZE, offset });
  const {
    register,
    handleSubmit,
    reset,
    control,
    getValues,
    setValue,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<SearchFilters>({
    resolver: zodResolver(searchSchema),
    defaultValues: applied,
  });
  const [date, start] = useWatch({ control, name: ['date', 'start'] });
  const endChoices = useMemo(() => bookingEndTimes(date, start), [date, start]);
  const allowedEnds = useMemo(() => new Set(endChoices.times), [endChoices]);
  const latestEnd = endChoices.times.at(-1);
  const endHint =
    !date || !start
      ? 'Choose a date and start time first.'
      : endChoices.error ||
        (latestEnd
          ? `Latest end time: ${latestEnd} Melbourne time, on the same day.`
          : 'No valid end time fits after this start on the same day. Choose another start time.');

  useEffect(() => {
    reset(filtersFromUrl(new URLSearchParams(urlState)));
  }, [urlState, reset]);

  function updateStart(field: 'date' | 'start', value: string) {
    const current = { ...getValues(), [field]: value };
    if (current.end && !bookingEndTimes(current.date, current.start).times.includes(current.end)) {
      setValue('end', '', { shouldDirty: true });
      setError('end', {
        type: 'selectionChanged',
        message: 'End time cleared because it no longer fits. Choose a new end time.',
      });
    }
  }

  function search(value: SearchFilters) {
    setSearchParams({
      date: value.date,
      start: value.start,
      end: value.end,
      capacity: String(value.capacity),
      offset: '0',
    });
  }

  function book(room: Room) {
    const params = new URLSearchParams({
      room_id: room.id,
      date: applied.date,
      start: applied.start,
      end: applied.end,
      capacity: String(applied.capacity),
      offset: String(offset),
    });
    navigate(`/review?${params.toString()}`);
  }

  function goToPage(nextOffset: number) {
    const next = new URLSearchParams(searchParams);
    next.set('offset', String(nextOffset));
    setSearchParams(next);
  }

  const page = rooms.data;
  const matching = page?.items.filter((room) => room.capacity >= applied.capacity) ?? [];
  const hasNext = Boolean(page && page.offset + page.limit < page.total);
  const lastOffset = Math.floor(Math.max(0, (page?.total ?? 0) - 1) / PAGE_SIZE) * PAGE_SIZE;
  const previousOffset = Math.max(0, Math.min(offset - PAGE_SIZE, lastOffset));
  const available = matching.filter((room) => room.active && room.available === true).length;
  const firstError =
    errors.date?.message ??
    errors.start?.message ??
    errors.end?.message ??
    errors.capacity?.message;
  const errorMessage = firstError ?? interval.error;
  // Cached availability must be checked again before offering a booking.
  const showResults = !interval.error && !rooms.isError && !rooms.isFetching && page;
  const paginated = offset > 0 || hasNext;
  const loadError = rooms.error instanceof ApiError ? rooms.error : undefined;
  let range = 'Choose a time to check availability.';
  if (interval.hasInterval) {
    range = `${formatCampusDate(applied.date)} · ${applied.start}–${applied.end}`;
  }

  return (
    <section data-page="find" aria-label="Find a room">
      <PageTitle title="Find a room" description="Choose a date, time, and group size." />
      <form
        className="sw-search"
        onSubmit={handleSubmit(search)}
        noValidate
        aria-label="Room search"
      >
        <label htmlFor={`${formId}-date`}>
          Date
          <input
            id={`${formId}-date`}
            type="date"
            required
            {...register('date', { onChange: (event) => updateStart('date', event.target.value) })}
            aria-invalid={Boolean(errors.date)}
            aria-describedby={errors.date ? `${formId}-error` : undefined}
          />
        </label>
        <label htmlFor={`${formId}-start`}>
          From
          <input
            id={`${formId}-start`}
            type="time"
            step={900}
            required
            {...register('start', {
              onChange: (event) => updateStart('start', event.target.value),
            })}
            aria-invalid={Boolean(errors.start)}
            aria-describedby={errors.start ? `${formId}-error` : undefined}
          />
        </label>
        <label htmlFor={`${formId}-end`}>
          Until
          <select
            id={`${formId}-end`}
            required
            disabled={!latestEnd}
            {...register('end', { onChange: () => clearErrors('end') })}
            aria-invalid={Boolean(errors.end)}
            aria-describedby={`${formId}-time-hint${errors.end ? ` ${formId}-error` : ''}`}
          >
            <option value="">Choose end time</option>
            <optgroup label="Available end times">
              {endChoices.times.map((time) => (
                <option key={time} value={time}>
                  {time}
                </option>
              ))}
            </optgroup>
            <optgroup label="Unavailable end times" disabled>
              {END_TIMES.filter((time) => !allowedEnds.has(time)).map((time) => (
                <option key={time} value={time} disabled>
                  {time}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        <label htmlFor={`${formId}-capacity`}>
          People
          <select
            id={`${formId}-capacity`}
            {...register('capacity', { valueAsNumber: true })}
            aria-invalid={Boolean(errors.capacity)}
            aria-describedby={errors.capacity ? `${formId}-error` : undefined}
          >
            {CAPACITIES.map((capacity) => (
              <option key={capacity} value={capacity}>
                {capacity === 1 ? 'Any size' : `${capacity} people`}
              </option>
            ))}
            {!CAPACITIES.includes(applied.capacity) && (
              <option value={applied.capacity}>{applied.capacity} people</option>
            )}
          </select>
        </label>
        <p
          id={`${formId}-time-hint`}
          className="sw-time-hint sw-small"
          role="status"
          aria-label="Booking duration"
        >
          Book for 30 minutes–2 hours. {endHint}
        </p>
        <Button variant="primary" type="submit" disabled={isSubmitting}>
          Find rooms
          <Search size={18} aria-hidden="true" />
        </Button>
      </form>
      {errorMessage && (
        <p id={`${formId}-error`} className="sw-error" role="alert">
          {errorMessage}
        </p>
      )}
      <div className="sw-results-top">
        <h2>
          {interval.hasInterval ? 'Available rooms' : 'Rooms'}
          {showResults && (
            <span className="sw-count" aria-live="polite">
              {interval.hasInterval
                ? `${available} of ${matching.length} available${paginated ? ' on this page' : ''}`
                : `${matching.length} rooms${paginated ? ' on this page' : ''}`}
            </span>
          )}
        </h2>
        <span className="sw-small">{range}</span>
      </div>
      {!interval.error && (rooms.isPending || rooms.isFetching) && (
        <StateMessage title="Loading rooms" message="Checking room information." />
      )}
      {!interval.error && rooms.isError && !rooms.isFetching && (
        <>
          <StateMessage
            title="Rooms could not be loaded"
            message={loadError?.message ?? 'Try again to get current room information.'}
            variant="error"
            onRetry={() => {
              void rooms.refetch();
            }}
          />
          {loadError?.requestId && <p className="sw-small">Request ID: {loadError.requestId}</p>}
        </>
      )}
      {showResults && (
        <>
          <div className="sw-rooms" aria-busy={rooms.isFetching}>
            {matching.map((room) => (
              <RoomCard
                key={room.id}
                room={room}
                filters={applied}
                hasInterval={interval.hasInterval}
                onBook={book}
              />
            ))}
            {matching.length === 0 && (
              <StateMessage
                title={
                  applied.capacity > 1 ? 'No matching rooms on this page' : 'No rooms on this page'
                }
                message={
                  hasNext
                    ? 'Try the next page or change the group size.'
                    : 'Change the group size or try another search.'
                }
              />
            )}
          </div>
          {paginated && (
            <nav className="sw-actions" aria-label="Room pages">
              <Button
                disabled={offset === 0 || rooms.isFetching}
                onClick={() => goToPage(previousOffset)}
              >
                Previous room page
              </Button>
              <span className="sw-small">Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
              <Button
                disabled={!hasNext || rooms.isFetching}
                onClick={() => goToPage(offset + PAGE_SIZE)}
              >
                Next room page
              </Button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
