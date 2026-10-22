import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useRoomDay } from '@/shared/api/queries';
import type { RoomDay } from '@/shared/api/client';
import { campusToday, toBookingInterval } from '@/shared/dates';
import { readCapacity, readOffset, searchPath } from '@/features/bookings/selection';
import { RoomIllustration } from '@/shared/illustrations';
import { Button, PageTitle, StateMessage } from '@/shared/ui';
import './rooms.css';

const TIMES = Array.from(
  { length: 96 },
  (_, i) => `${Math.floor(i / 4)}`.padStart(2, '0') + ':' + `${(i % 4) * 15}`.padStart(2, '0'),
);
const PERIODS = [
  'Night · 00:00–05:45',
  'Morning · 06:00–11:45',
  'Afternoon · 12:00–17:45',
  'Evening · 18:00–23:45',
];
const REASONS: Record<NonNullable<RoomDay['slots'][number]['unavailable_reason']>, string> = {
  inactive: 'Inactive',
  schedule_unconfirmed: 'Hours unconfirmed',
  past: 'Past',
  outside_horizon: 'Beyond 14 days',
  invalid_local_time: 'DST change',
  unavailable: 'Unavailable',
};

type Choice = { time: string; enabled: boolean; label: string; inRange?: boolean };
function TimeChoices({
  name,
  choices,
  selected,
  onSelect,
  checking,
}: {
  name: string;
  choices: Choice[];
  selected: string;
  onSelect: (time: string) => void;
  checking: boolean;
}) {
  return (
    <fieldset className="sw-time-choices">
      <legend>{name === 'start' ? 'Start time' : 'End time'}</legend>
      {PERIODS.map((period, index) => {
        const group = choices.slice(index * 24, (index + 1) * 24);
        const count = group.filter((choice) => choice.enabled).length;
        return (
          <details
            key={period}
            open={count > 0 || group.some((choice) => choice.time === selected)}
          >
            <summary>
              {period}
              <span className="sw-small">{checking ? 'Checking' : `${count} choices`}</span>
            </summary>
            <div className="sw-time-grid">
              {group.map((choice) => (
                <label
                  key={choice.time}
                  className={`sw-time-choice${choice.inRange ? ' in-range' : ''}`}
                >
                  <input
                    type="radio"
                    name={name}
                    value={choice.time}
                    checked={selected === choice.time}
                    disabled={!choice.enabled || checking}
                    onChange={() => onSelect(choice.time)}
                  />
                  <span>
                    <strong>{choice.time}</strong>{' '}
                    <small>
                      {checking
                        ? 'Checking'
                        : selected === choice.time
                          ? `Selected${!choice.enabled ? ' · unavailable' : ''}`
                          : choice.label}
                    </small>
                  </span>
                </label>
              ))}
            </div>
          </details>
        );
      })}
    </fieldset>
  );
}

export function RoomBookingPage() {
  const { roomId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const date = params.get('date') ?? campusToday();
  const start = params.get('start') ?? '';
  const end = params.get('end') ?? '';
  const capacity = readCapacity(params);
  const day = useRoomDay(roomId, date);
  const data = day.data;
  const [clock, setClock] = useState(Date.now);
  const [notice, setNotice] = useState('');
  const chosenStart = data?.slots.find((slot) => slot.time === start);
  const chosenEnd = chosenStart?.valid_ends.find((choice) => choice.time === end);
  const age = Math.max(0, clock - day.dataUpdatedAt);
  const serverNow = data ? Date.parse(data.generated_at) + age : Infinity;
  const fresh = Boolean(data && !day.isFetching && !day.isError && age < 30_000);
  const future = Boolean(chosenStart?.starts_at && Date.parse(chosenStart.starts_at) > serverNow);
  const valid =
    fresh &&
    future &&
    chosenStart?.available &&
    chosenEnd &&
    data &&
    capacity <= data.room.capacity;
  const duration =
    chosenStart?.starts_at && chosenEnd
      ? (Date.parse(chosenEnd.ends_at) - Date.parse(chosenStart.starts_at)) / 60_000
      : 0;

  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (params.has('date')) return;
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set('date', date);
        return next;
      },
      { replace: true },
    );
  }, [params, date, setParams]);
  // Only the successful response for this query key may invalidate this selection.
  useEffect(() => {
    if (!data || day.isFetching || day.isError || !end || chosenEnd) return;
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete('end');
        return next;
      },
      { replace: true, state: { availabilityChanged: true } },
    );
  }, [data, day.isFetching, day.isError, end, chosenEnd, setParams]);

  function choose(field: 'date' | 'start' | 'end', value: string) {
    const next = new URLSearchParams(params);
    next.set('date', date);
    next.set(field, value);
    setNotice('');
    if (field === 'date') {
      next.delete('start');
      next.delete('end');
    }
    if (
      field === 'start' &&
      end &&
      !data?.slots
        .find((slot) => slot.time === value)
        ?.valid_ends.some((choice) => choice.time === end)
    ) {
      next.delete('end');
      setNotice('End time cleared because it no longer fits. Choose a new end time.');
    }
    setParams(next);
  }
  function review() {
    if (!valid) return;
    // Keep offset-aware timestamps consistent with the existing review/create contract.
    try {
      toBookingInterval({ date, start, end });
    } catch {
      return;
    }
    navigate(
      `/review?${new URLSearchParams({ room_id: roomId, date, start, end, capacity: String(capacity), offset: String(readOffset(params)) })}`,
    );
  }
  const startChoices: Choice[] = (data?.slots ?? []).map((slot) => {
    const passed = Boolean(slot.starts_at && Date.parse(slot.starts_at) <= serverNow);
    return {
      time: slot.time,
      enabled: slot.available && !passed,
      label: passed
        ? 'Past'
        : slot.available
          ? 'Available'
          : REASONS[slot.unavailable_reason ?? 'unavailable'],
      inRange: Boolean(chosenEnd && slot.time >= start && slot.time < end),
    };
  });
  const endChoices: Choice[] = TIMES.map((time) => ({
    time,
    enabled: Boolean(future && chosenStart?.valid_ends.some((choice) => choice.time === time)),
    label: !start
      ? 'Choose start'
      : chosenStart?.valid_ends.some((choice) => choice.time === time) && future
        ? 'Available'
        : 'Unavailable',
    inRange: Boolean(chosenEnd && time > start && time <= end),
  }));

  return (
    <section data-page="room-schedule" aria-label="Choose room time">
      <PageTitle
        title="Choose time"
        description="Choose a date, then a start and end time. All times are in Melbourne."
      />
      <Button onClick={() => navigate(searchPath(params))}>Back to rooms</Button>
      {data && (
        <div className="sw-schedule-room">
          <RoomIllustration room={data.room} />
          <div>
            <h2>{data.room.name}</h2>
            <p>
              {data.room.location} · {data.room.capacity} people
            </p>
            <p className="sw-small">30 minutes–2 hours · 15-minute choices · Same day</p>
          </div>
        </div>
      )}
      <label className="sw-schedule-date">
        Date
        <input
          type="date"
          value={date}
          min={data ? campusToday(data.generated_at) : campusToday()}
          max={data ? campusToday(data.booking_window_ends_at) : undefined}
          onChange={(event) => choose('date', event.target.value)}
        />
      </label>
      {day.isPending && (
        <StateMessage title="Loading availability" message="Checking this room’s schedule." />
      )}
      {day.isError && (
        <StateMessage
          title="Availability could not be loaded"
          message="Your selection is kept. Retry to check this room’s times."
          variant="error"
          onRetry={() => void day.refetch()}
        />
      )}
      {data && !day.isError && (
        <>
          <p role="status" className="sw-small">
            {!fresh
              ? 'Checking current availability…'
              : 'Availability checked. Updates every 30 seconds.'}
          </p>
          {!data.slots.some((slot) => slot.available) && (
            <StateMessage
              title="No available starts on this date"
              message={
                data.slots.some((slot) => slot.unavailable_reason === 'schedule_unconfirmed')
                  ? 'Room hours have not been confirmed. Try another room.'
                  : 'Choose another date or room. Greyed-out times cannot be selected.'
              }
            />
          )}
          <p className="sw-small">
            Unavailable times may be occupied, outside room hours, or too short for a continuous
            30-minute booking.
          </p>
          <div className="sw-slot-columns">
            <TimeChoices
              name="start"
              choices={startChoices}
              selected={start}
              onSelect={(value) => choose('start', value)}
              checking={!fresh}
            />
            <TimeChoices
              name="end"
              choices={endChoices}
              selected={end}
              onSelect={(value) => choose('end', value)}
              checking={!fresh}
            />
          </div>
        </>
      )}
      <div className="sw-slot-summary">
        <div aria-live="polite">
          {(notice || location.state?.availabilityChanged) && (
            <p>
              {notice || 'End time cleared because it is no longer available. Choose a new time.'}
            </p>
          )}
          <p>
            {chosenEnd
              ? `${start}–${end} · ${duration} minutes`
              : start
                ? `Start ${start}. Choose an available end time.`
                : 'Choose a start and end time.'}
          </p>
          {start && chosenStart && !future && (
            <p>That start time has passed. Choose a later time.</p>
          )}
          {data && capacity > data.room.capacity && (
            <p className="sw-error">This room is too small for your group. Choose another room.</p>
          )}
        </div>
        <Button variant="primary" disabled={!valid} onClick={review}>
          Review booking
        </Button>
      </div>
    </section>
  );
}
