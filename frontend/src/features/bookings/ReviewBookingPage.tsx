import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useMutationState } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useCreateBooking, useRoom } from '@/shared/api/queries';
import { ApiError } from '@/shared/api/client';
import { campusToday, formatCampusDate, toCampusInterval } from '@/shared/dates';
import { RoomIllustration } from '@/shared/illustrations/RoomIllustration';
import { Button, PageTitle, StateMessage } from '@/shared/ui';
import { bookingFeedback, type BookingFeedback } from './booking-error';
import { readBookingSelection, searchPath, type BookingSelection } from './selection';
import './bookings.css';

function matchesSelection(variables: unknown, selection: BookingSelection | null) {
  if (!selection || typeof variables !== 'object' || variables === null) return false;
  if (!('room_id' in variables) || !('starts_at' in variables) || !('ends_at' in variables))
    return false;
  const interval = toCampusInterval(selection);
  return (
    variables.room_id === selection.roomId &&
    typeof variables.starts_at === 'string' &&
    typeof variables.ends_at === 'string' &&
    Date.parse(variables.starts_at) === Date.parse(interval.starts_at) &&
    Date.parse(variables.ends_at) === Date.parse(interval.ends_at)
  );
}

export function ReviewBookingPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { selection, error: selectionError } = useMemo(
    () => readBookingSelection(params),
    [params],
  );
  const fallback = { date: campusToday(), start: '13:00', end: '14:00', capacity: 1 };
  const roomQuery = useRoom(selection?.roomId ?? '', selection ?? fallback, Boolean(selection));
  const createBooking = useCreateBooking();
  const submissions = useMutationState({
    filters: { mutationKey: ['bookings', 'create'] },
    select: (mutation) => ({
      status: mutation.state.status,
      variables: mutation.state.variables,
      error: mutation.state.error,
    }),
  });
  const submissionLock = useRef(false);
  const mounted = useRef(false);
  const [feedback, setFeedback] = useState<BookingFeedback | null>(null);
  const matchingSubmissions = submissions.filter((submission) =>
    matchesSelection(submission.variables, selection),
  );
  const creating =
    createBooking.isPending ||
    matchingSubmissions.some((submission) => submission.status === 'pending');
  const priorUncertain = matchingSubmissions.some(
    (submission) =>
      submission.status === 'error' &&
      submission.error instanceof ApiError &&
      submission.error.uncertain,
  );
  const uncertain =
    params.get('outcome') === 'unknown' || feedback?.uncertain === true || priorUncertain;
  const room = roomQuery.data;
  const unavailable = room?.active === false || room?.available === false;
  const exceedsCapacity = Boolean(room && selection && selection.capacity > room.capacity);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (priorUncertain && params.get('outcome') !== 'unknown') {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.set('outcome', 'unknown');
          return next;
        },
        { replace: true },
      );
    }
  }, [priorUncertain, params, setParams]);

  async function confirmBooking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !selection ||
      !room ||
      unavailable ||
      exceedsCapacity ||
      uncertain ||
      submissionLock.current ||
      creating
    ) {
      return;
    }
    submissionLock.current = true;
    setFeedback(null);
    try {
      const interval = toCampusInterval(selection);
      await createBooking.mutateAsync({ room_id: room.id, ...interval });
      if (!mounted.current) return;
      navigate(`/bookings?${new URLSearchParams({ date: selection.date }).toString()}`, {
        state: {
          notice: `Booking confirmed: ${room.name}, ${formatCampusDate(selection.date)}, ${selection.start}–${selection.end}.`,
        },
      });
    } catch (error) {
      if (!mounted.current) return;
      const nextFeedback = bookingFeedback(error);
      setFeedback(nextFeedback);
      if (nextFeedback.uncertain) {
        setParams(
          (current) => {
            const next = new URLSearchParams(current);
            next.set('outcome', 'unknown');
            return next;
          },
          { replace: true },
        );
      }
    } finally {
      submissionLock.current = false;
    }
  }

  function checkBookings() {
    if (selection) {
      navigate(`/bookings?${new URLSearchParams({ date: selection.date }).toString()}`);
    }
  }

  return (
    <section className="sw-review" data-page="review" aria-label="Review booking">
      <PageTitle title="Review booking" description="Check the room and time before confirming." />
      {selectionError ? (
        <>
          <StateMessage title="Check your selection" message={selectionError} variant="error" />
          <Button onClick={() => navigate(searchPath(params))}>Back to search</Button>
        </>
      ) : roomQuery.isPending ? (
        <StateMessage title="Loading room" message="Checking the selected room and time." />
      ) : roomQuery.isError || !room ? (
        <>
          <StateMessage
            title="Room details unavailable"
            message="Your selection is kept. Refresh the room details or return to search."
            variant="error"
            onRetry={() => void roomQuery.refetch()}
          />
          <Button onClick={() => navigate(searchPath(params))}>Back to search</Button>
        </>
      ) : selection ? (
        <>
          {feedback ? (
            <StateMessage title={feedback.title} message={feedback.message} variant="error" />
          ) : uncertain ? (
            <StateMessage
              title="Booking outcome not confirmed"
              message="The request may have completed. Check bookings before creating another booking for this room and time."
              variant="error"
            />
          ) : unavailable ? (
            <StateMessage
              title="Room no longer available"
              message="Your selection is kept. Choose another room or time."
              variant="error"
            />
          ) : exceedsCapacity ? (
            <StateMessage
              title="Group exceeds room capacity"
              message="Choose a room with enough places for the selected group size."
              variant="error"
            />
          ) : null}
          <div className="sw-review-layout">
            <RoomIllustration room={room} />
            <form
              onSubmit={(event) => void confirmBooking(event)}
              aria-label="Confirm room booking"
            >
              <h2>{room.name}</h2>
              <p className="sw-small">{room.location}</p>
              <dl className="sw-summary">
                <div>
                  <dt>Date</dt>
                  <dd>{formatCampusDate(selection.date)}</dd>
                </div>
                <div>
                  <dt>Time</dt>
                  <dd>
                    {selection.start}–{selection.end}
                  </dd>
                </div>
                <div>
                  <dt>Capacity</dt>
                  <dd>{room.capacity} people</dd>
                </div>
                <div>
                  <dt>Time zone</dt>
                  <dd>Melbourne</dd>
                </div>
              </dl>
              <div className="sw-actions">
                <Button disabled={creating} onClick={() => navigate(searchPath(params))}>
                  Back
                </Button>
                {uncertain ? (
                  <Button variant="primary" onClick={checkBookings}>
                    Check bookings
                    <ArrowRight aria-hidden="true" />
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    type="submit"
                    disabled={creating || unavailable || exceedsCapacity}
                    aria-busy={creating}
                  >
                    {creating ? 'Confirming booking' : 'Confirm booking'}
                    <ArrowRight aria-hidden="true" />
                  </Button>
                )}
              </div>
            </form>
          </div>
        </>
      ) : null}
    </section>
  );
}
