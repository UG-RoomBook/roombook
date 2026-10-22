import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useMutationState } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useRoom } from '@/shared/api/queries';
import type { CreatedBooking } from '@/shared/api/client';
import { useAccountSession } from '@/features/accounts/session';
import type { AccountSession } from '@/features/accounts/api';
import { campusToday, formatCampusDate, toBookingInterval } from '@/shared/dates';
import { RoomIllustration } from '@/shared/illustrations/RoomIllustration';
import { Button, PageTitle, StateMessage } from '@/shared/ui';
import { bookingFeedback, type BookingFeedback } from './booking-error';
import { readBookingSelection, searchPath } from './selection';
import { loadAttempt, useCreateBooking } from './submission';
import './bookings.css';

export function ReviewBookingPage() {
  const session = useAccountSession();
  const [params] = useSearchParams();
  const identity = !session.isError ? session.data?.user.id : undefined;
  return (
    <ReviewContent
      key={`${identity ?? 'guest'}:${params.get('room_id')}:${params.get('date')}:${params.get('start')}:${params.get('end')}`}
      session={session.isError ? null : (session.data ?? null)}
      sessionPending={session.isPending}
      sessionError={session.error}
      retrySession={() => void session.refetch()}
    />
  );
}

function ReviewContent({
  session,
  sessionPending,
  sessionError,
  retrySession,
}: {
  session: AccountSession | null;
  sessionPending: boolean;
  sessionError: Error | null;
  retrySession: () => void;
}) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { selection, error: selectionError } = useMemo(
    () => readBookingSelection(params),
    [params],
  );
  const fallback = { date: campusToday(), start: '13:00', end: '14:00', capacity: 1 };
  const roomQuery = useRoom(selection?.roomId ?? '', selection ?? fallback, Boolean(selection));
  const mutation = useCreateBooking();
  const submissions = useMutationState({
    filters: { mutationKey: ['bookings', 'create'] },
    select: (item) => ({ status: item.state.status, variables: item.state.variables }),
  });
  const lock = useRef(false);
  const mounted = useRef(false);
  const [receipt, setReceipt] = useState<CreatedBooking | null>(null);
  const [retryReady, setRetryReady] = useState(true);
  const [feedback, setFeedback] = useState<BookingFeedback | null>(null);
  const body = selection ? { room_id: selection.roomId, ...toBookingInterval(selection) } : null;
  const matching = submissions.filter(({ variables }) => {
    if (!session || !body || !variables || typeof variables !== 'object') return false;
    const value = variables as { ownerId?: string; body?: typeof body };
    return (
      value.ownerId === session.user.id &&
      value.body?.room_id === body.room_id &&
      value.body.starts_at === body.starts_at &&
      value.body.ends_at === body.ends_at
    );
  });
  let saved = null;
  let storageError: Error | null = null;
  try {
    if (session && body) saved = loadAttempt(session.user.id, body);
  } catch (error) {
    storageError = error as Error;
  }
  const creating = mutation.isPending || matching.some((item) => item.status === 'pending');
  const confirmed = receipt ?? saved?.receipt;
  const uncertain = saved?.state === 'pending' || feedback?.uncertain === true;
  const lostAttempt = params.get('outcome') === 'unknown' && !saved;
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
    if (retryReady) return;
    const timer = setTimeout(() => setRetryReady(true), 1000);
    return () => clearTimeout(timer);
  }, [retryReady]);

  async function confirmBooking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !selection ||
      !body ||
      !session ||
      confirmed ||
      storageError ||
      lostAttempt ||
      ((!room || unavailable || exceedsCapacity) && !uncertain) ||
      lock.current ||
      creating ||
      !retryReady
    )
      return;
    lock.current = true;
    setFeedback(null);
    try {
      const result = await mutation.mutateAsync({ ownerId: session.user.id, body });
      if (mounted.current) {
        setReceipt(result);
        setParams(
          (current) => {
            const value = new URLSearchParams(current);
            value.delete('outcome');
            return value;
          },
          { replace: true },
        );
      }
    } catch (error) {
      if (!mounted.current) return;
      const next = bookingFeedback(error);
      setFeedback(next);
      if (next.uncertain) {
        setRetryReady(false);
        setParams(
          (current) => {
            const value = new URLSearchParams(current);
            value.set('outcome', 'unknown');
            return value;
          },
          { replace: true },
        );
      }
    } finally {
      lock.current = false;
    }
  }
  const signIn = () =>
    navigate(`/account/login?${new URLSearchParams({ next: `/review?${params}` })}`);
  const back = () => navigate(searchPath(params));
  const feedbackView = sessionPending ? (
    <StateMessage title="Checking your session" message="Please wait before confirming." />
  ) : sessionError ? (
    <StateMessage
      title="Session unavailable"
      message="Your selection is kept. Check your session before confirming."
      variant="error"
      onRetry={retrySession}
    />
  ) : !session ? (
    <StateMessage
      title="Sign in to book"
      message="Use a verified, active account. Your room and time will be kept."
    />
  ) : storageError ? (
    <StateMessage
      title="Saved attempt unavailable"
      message={storageError.message}
      variant="error"
    />
  ) : lostAttempt ? (
    <StateMessage
      title="Booking outcome not confirmed"
      message="The saved request key is missing. Return to the original tab or contact support before creating another reservation for this time."
      variant="error"
    />
  ) : feedback ? (
    <StateMessage title={feedback.title} message={feedback.message} variant="error" />
  ) : uncertain ? (
    <StateMessage
      title="Booking outcome not confirmed"
      message="The request may have completed. Retry this saved attempt to confirm the original result. Keep this tab until the outcome is known."
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
  ) : null;
  const submit = !session ? (
    <Button variant="primary" onClick={signIn} disabled={sessionPending}>
      Sign in to book
    </Button>
  ) : (
    <Button
      variant="primary"
      type="submit"
      disabled={
        creating ||
        !retryReady ||
        Boolean(storageError) ||
        lostAttempt ||
        Boolean(sessionError) ||
        (!uncertain && (unavailable || exceedsCapacity))
      }
      aria-busy={creating}
    >
      {creating ? 'Confirming booking' : uncertain ? 'Retry saved booking' : 'Confirm booking'}
      <ArrowRight aria-hidden="true" />
    </Button>
  );
  return (
    <section className="sw-review" data-page="review" aria-label="Review booking">
      <PageTitle title="Review booking" description="Check the room and time before confirming." />
      {selectionError ? (
        <>
          <StateMessage title="Check your selection" message={selectionError} variant="error" />
          <Button onClick={back}>Back to search</Button>
        </>
      ) : confirmed && selection ? (
        <>
          <div role="status" className="sw-booking-receipt">
            <h2>Booking confirmed</h2>
            <p>
              {room?.name ?? 'Selected room'} · {formatCampusDate(selection.date)} ·{' '}
              {selection.start}–{selection.end} Melbourne
            </p>
            <p>
              Booking reference: <strong>{confirmed.id}</strong>
            </p>
            <p>
              Keep this booking reference. Booking history and cancellation are not available yet.
            </p>
          </div>
          <Button onClick={back}>Back to search</Button>
        </>
      ) : roomQuery.isPending ? (
        <StateMessage title="Loading room" message="Checking the selected room and time." />
      ) : (roomQuery.isError || !room) && !uncertain ? (
        <>
          <StateMessage
            title="Room details unavailable"
            message="Your selection is kept. Refresh the room details or return to search."
            variant="error"
            onRetry={() => void roomQuery.refetch()}
          />
          <Button onClick={back}>Back to search</Button>
        </>
      ) : selection ? (
        <>
          {feedbackView}
          <div className="sw-review-layout">
            {room && <RoomIllustration room={room} />}
            <form
              onSubmit={(event) => void confirmBooking(event)}
              aria-label="Confirm room booking"
            >
              <h2>{room?.name ?? 'Selected room'}</h2>
              <p className="sw-small">{room?.location}</p>
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
                {room && (
                  <div>
                    <dt>Capacity</dt>
                    <dd>{room.capacity} people</dd>
                  </div>
                )}
                <div>
                  <dt>Time zone</dt>
                  <dd>Melbourne</dd>
                </div>
              </dl>
              <div className="sw-actions">
                <Button disabled={creating} onClick={back}>
                  Back
                </Button>
                {submit}
              </div>
            </form>
          </div>
        </>
      ) : null}
    </section>
  );
}
