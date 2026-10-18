import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useLocation, useSearchParams } from 'react-router-dom';
import { useBookingList, useCancelBooking, useRoomCatalog } from '@/shared/api/queries';
import type { Booking, Room } from '@/shared/api/types';
import { campusToday, formatCampusDate, formatCampusTime } from '@/shared/dates';
import { Button, PageTitle, StateMessage } from '@/shared/ui';
import { cancellationFeedback, type BookingFeedback } from './booking-error';
import { bookingDateSchema, readOffset, type BookingDateValues } from './selection';
import './bookings.css';

const PAGE_SIZE = 20;

type BookingRowProps = {
  booking: Booking;
  room: Room | undefined;
  onNotice: (notice: string) => void;
  onRefresh: () => Promise<unknown>;
};

function BookingRow({ booking, room, onNotice, onRefresh }: BookingRowProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [feedback, setFeedback] = useState<BookingFeedback | null>(null);
  const cancelBooking = useCancelBooking();
  const cancelButton = useRef<HTMLButtonElement>(null);
  const keepButton = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const submissionLock = useRef(false);
  const focusAfterCancellation = useRef(false);
  const isCancelled =
    booking.status === 'cancelled' ||
    (cancelBooking.data?.id === booking.id && cancelBooking.data?.status === 'cancelled');
  const roomName = room?.name ?? `Room ${booking.room_id}`;
  const confirmationId = `cancel-${booking.id}`;

  useEffect(() => {
    if (confirmOpen && !isCancelled) keepButton.current?.focus();
  }, [confirmOpen, isCancelled]);

  useEffect(() => {
    if (isCancelled && focusAfterCancellation.current) {
      heading.current?.focus();
      focusAfterCancellation.current = false;
    }
  }, [isCancelled, confirmOpen]);

  function keepBooking() {
    if (cancelBooking.isPending) return;
    setConfirmOpen(false);
    setFeedback(null);
    cancelButton.current?.focus();
  }

  async function releaseBooking() {
    if (cancelBooking.isPending || submissionLock.current || isCancelled) return;
    submissionLock.current = true;
    setFeedback(null);
    try {
      await cancelBooking.mutateAsync(booking.id);
      focusAfterCancellation.current = true;
      setConfirmOpen(false);
      onNotice(
        `Booking cancelled: ${roomName}, ${formatCampusDate(booking.starts_at)}, ${formatCampusTime(booking.starts_at)}–${formatCampusTime(booking.ends_at)}.`,
      );
    } catch (error) {
      setFeedback(cancellationFeedback(error));
    } finally {
      submissionLock.current = false;
    }
  }

  return (
    <article className="sw-booking" aria-labelledby={`booking-${booking.id}`}>
      <div>
        <h3 id={`booking-${booking.id}`} tabIndex={-1} ref={heading}>
          {roomName}
        </h3>
        <p className="sw-small">
          {formatCampusDate(booking.starts_at)} · {formatCampusTime(booking.starts_at)}–
          {formatCampusTime(booking.ends_at)}
        </p>
      </div>
      <div className="sw-actions">
        <span className={`sw-status${isCancelled ? ' busy' : ''}`}>
          {isCancelled ? 'Cancelled' : 'Confirmed'}
        </span>
        {!isCancelled && (
          <Button
            ref={cancelButton}
            aria-expanded={confirmOpen}
            aria-controls={confirmOpen ? confirmationId : undefined}
            onClick={() => {
              setConfirmOpen(true);
              setFeedback(null);
            }}
            disabled={cancelBooking.isPending}
          >
            Cancel booking
          </Button>
        )}
      </div>
      {confirmOpen && !isCancelled && (
        <div
          className="sw-confirm-cancel"
          id={confirmationId}
          role="group"
          aria-label={`Cancel ${roomName} reservation`}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              keepBooking();
            }
          }}
        >
          <p className="sw-small">Cancel this reservation and release the room?</p>
          <div className="sw-actions">
            <Button ref={keepButton} disabled={cancelBooking.isPending} onClick={keepBooking}>
              Keep booking
            </Button>
            <Button
              disabled={cancelBooking.isPending}
              aria-busy={cancelBooking.isPending}
              onClick={() => void releaseBooking()}
            >
              {cancelBooking.isPending ? 'Cancelling booking' : 'Yes, cancel'}
            </Button>
          </div>
        </div>
      )}
      {feedback && !isCancelled && (
        <div className="sw-booking-feedback">
          <StateMessage title={feedback.title} message={feedback.message} variant="error" />
          <Button onClick={() => void onRefresh()}>Refresh bookings</Button>
        </div>
      )}
    </article>
  );
}

function locationNotice(state: unknown): string {
  if (typeof state !== 'object' || state === null || !('notice' in state)) return '';
  return typeof state.notice === 'string' ? state.notice : '';
}

export function BookingsPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const selectedDate = params.get('date') ?? campusToday();
  const parsedDate = bookingDateSchema.safeParse({ date: selectedDate });
  const offset = readOffset(params);
  const bookings = useBookingList(
    parsedDate.success ? parsedDate.data.date : campusToday(),
    undefined,
    {
      limit: PAGE_SIZE,
      offset,
    },
  );
  const rooms = useRoomCatalog();
  const [notice, setNotice] = useState(() => locationNotice(location.state));
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<BookingDateValues>({
    resolver: zodResolver(bookingDateSchema),
    defaultValues: { date: selectedDate },
  });

  useEffect(() => {
    reset({ date: selectedDate });
  }, [selectedDate, reset]);

  function filterBookings(values: BookingDateValues) {
    const next = new URLSearchParams(params);
    next.set('date', values.date);
    next.delete('offset');
    setNotice('');
    setParams(next);
  }

  function changePage(nextOffset: number) {
    const next = new URLSearchParams(params);
    next.set('date', selectedDate);
    if (nextOffset === 0) next.delete('offset');
    else next.set('offset', String(nextOffset));
    setParams(next);
  }

  const list = bookings.data;
  const initialLoading = bookings.isPending || (rooms.isPending && Boolean(list?.items.length));
  const hasNext = Boolean(list && offset + list.items.length < list.total);

  return (
    <section data-page="bookings" aria-label="Bookings">
      <PageTitle title="Bookings" description="Shared room reservations." />
      <form
        className="sw-booking-filter"
        aria-label="Filter bookings"
        onSubmit={(event) => void handleSubmit(filterBookings)(event)}
        noValidate
      >
        <label htmlFor="bookings-date">
          Date
          <input
            id="bookings-date"
            type="date"
            {...register('date')}
            aria-invalid={Boolean(errors.date)}
            aria-describedby={errors.date ? 'bookings-date-error' : undefined}
          />
        </label>
        <Button type="submit">Show bookings</Button>
        {errors.date && (
          <p className="sw-error" id="bookings-date-error" role="alert">
            {errors.date.message}
          </p>
        )}
      </form>
      {notice && (
        <div className="sw-notice" role="status">
          {notice}
        </div>
      )}
      {!parsedDate.success ? (
        <StateMessage
          title="Check the date"
          message="Choose a valid date to view bookings."
          variant="error"
        />
      ) : initialLoading ? (
        <StateMessage title="Loading bookings" />
      ) : bookings.isError ? (
        <StateMessage
          title="Bookings unavailable"
          message="The reservation list could not be loaded. Try again."
          variant="error"
          onRetry={() => void bookings.refetch()}
        />
      ) : list ? (
        <>
          {rooms.isError && list.items.length > 0 && (
            <StateMessage
              title="Room names unavailable"
              message="Reservations are shown using their room IDs. You can still check status and cancel."
              variant="error"
              onRetry={() => void rooms.refetch()}
            />
          )}
          {bookings.isFetching && (
            <p className="sw-small" role="status">
              Updating bookings
            </p>
          )}
          {list.items.length === 0 ? (
            <StateMessage
              title="No bookings"
              message={
                offset > 0
                  ? 'There are no reservations on this page. Return to the previous page.'
                  : 'No reservations for this date.'
              }
            />
          ) : (
            <div className="sw-booking-list" aria-busy={bookings.isFetching}>
              {list.items.map((booking) => (
                <BookingRow
                  key={booking.id}
                  booking={booking}
                  room={rooms.data?.find((room) => room.id === booking.room_id)}
                  onNotice={setNotice}
                  onRefresh={() => bookings.refetch()}
                />
              ))}
            </div>
          )}
          {(offset > 0 || hasNext) && (
            <nav className="sw-booking-pagination" aria-label="Booking pages">
              <p className="sw-small">
                {list.items.length > 0
                  ? `${offset + 1}–${offset + list.items.length} of ${list.total}`
                  : `${list.total} reservations`}
              </p>
              <div className="sw-actions">
                <Button
                  disabled={offset === 0 || bookings.isFetching}
                  onClick={() => changePage(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </Button>
                <Button
                  disabled={!hasNext || bookings.isFetching}
                  onClick={() => changePage(offset + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </nav>
          )}
        </>
      ) : null}
    </section>
  );
}
