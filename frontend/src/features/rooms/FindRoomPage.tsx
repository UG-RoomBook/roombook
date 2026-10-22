import { useNavigate, useSearchParams } from 'react-router-dom';
import { useRooms } from '@/shared/api/queries';
import { ApiError } from '@/shared/api/client';
import { readCapacity, readOffset } from '@/features/bookings/selection';
import { Button, PageTitle, StateMessage } from '@/shared/ui';
import { RoomCard } from './RoomCard';
import './rooms.css';

const PAGE_SIZE = 20;
const CAPACITIES = [1, 4, 6, 8];

export function FindRoomPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const capacity = readCapacity(params);
  const offset = readOffset(params);
  const rooms = useRooms({ date: '', start: '', end: '', capacity }, true, {
    limit: PAGE_SIZE,
    offset,
  });
  const page = rooms.data;
  const matching = page?.items.filter((room) => room.capacity >= capacity) ?? [];
  const hasNext = Boolean(page && page.offset + page.limit < page.total);
  const lastOffset = Math.floor(Math.max(0, (page?.total ?? 0) - 1) / PAGE_SIZE) * PAGE_SIZE;
  const loadError = rooms.error instanceof ApiError ? rooms.error : undefined;
  const showResults = !rooms.isError && !rooms.isFetching && page;
  const paginated = offset > 0 || hasNext;

  return (
    <section data-page="find" aria-label="Find a room">
      <PageTitle title="Find a room" description="Choose your room, then pick an available time." />
      <div className="sw-room-filter">
        <label>
          People
          <select
            value={capacity}
            onChange={(event) => setParams({ capacity: event.target.value, offset: '0' })}
          >
            {CAPACITIES.map((value) => (
              <option key={value} value={value}>
                {value === 1 ? 'Any size' : `${value} people`}
              </option>
            ))}
            {!CAPACITIES.includes(capacity) && <option value={capacity}>{capacity} people</option>}
          </select>
        </label>
        <p className="sw-small">Book for 30 minutes–2 hours. All times are in Melbourne.</p>
      </div>
      <div className="sw-results-top">
        <h2>
          Rooms{' '}
          {showResults && (
            <span className="sw-count" aria-live="polite">
              {matching.length} rooms{paginated ? ' on this page' : ''}
            </span>
          )}
        </h2>
      </div>
      {(rooms.isPending || rooms.isFetching) && (
        <StateMessage title="Loading rooms" message="Checking room information." />
      )}
      {rooms.isError && !rooms.isFetching && (
        <>
          <StateMessage
            title="Rooms could not be loaded"
            message={loadError?.message ?? 'Try again to get current room information.'}
            variant="error"
            onRetry={() => void rooms.refetch()}
          />
          {loadError?.requestId && <p className="sw-small">Request ID: {loadError.requestId}</p>}
        </>
      )}
      {showResults && (
        <>
          <div className="sw-rooms">
            {matching.map((room) => (
              <RoomCard
                key={room.id}
                room={room}
                onChooseTime={() =>
                  navigate(
                    `/rooms/${room.id}?${new URLSearchParams({ capacity: String(capacity), offset: String(offset) })}`,
                  )
                }
              />
            ))}
            {!matching.length && (
              <StateMessage
                title={capacity > 1 ? 'No matching rooms on this page' : 'No rooms on this page'}
                message={
                  hasNext
                    ? 'Try the next page or change the group size.'
                    : 'Change the group size or return to the previous page.'
                }
              />
            )}
          </div>
          {paginated && (
            <nav className="sw-actions" aria-label="Room pages">
              <Button
                disabled={offset === 0}
                onClick={() =>
                  setParams({
                    capacity: String(capacity),
                    offset: String(Math.max(0, Math.min(offset - PAGE_SIZE, lastOffset))),
                  })
                }
              >
                Previous room page
              </Button>
              <span className="sw-small">Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
              <Button
                disabled={!hasNext}
                onClick={() =>
                  setParams({ capacity: String(capacity), offset: String(offset + PAGE_SIZE) })
                }
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
