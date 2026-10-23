import { useAdminQuery, useFilters } from './hooks';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { Plus, ArrowUpRight, Users } from 'lucide-react';
import { RoomIllustration } from '@/shared/illustrations';
import { PageTitle } from '@/shared/ui/PageTitle';
import { Button } from '@/shared/ui/Button';
import { useAccountSession } from '@/features/accounts/session';
import type { RoomCreate, RoomUpdate } from '@/shared/api/generated/types.gen';
import { adminApi, type Room, type Impact } from './api';
import {
  ConfirmAction,
  Empty,
  ErrorNotice,
  Pagination,
  QueryState,
  ReasonField,
  SearchBox,
  Status,
} from './shared';

export function RoomsPage({ schedules = false }: { schedules?: boolean }) {
  const filters = useFilters();
  const query = { offset: filters.offset, limit: 20, search: filters.search };
  const rooms = useAdminQuery(['rooms', query], (signal) => adminApi.rooms(query, signal));
  return (
    <section>
      <PageTitle
        title={schedules ? 'Schedules' : 'Rooms'}
        description={
          schedules
            ? 'Set the hours that make a room available.'
            : 'Make space for a productive day.'
        }
      >
        {!schedules && (
          <Link className="sw-btn sw-primary" to="/admin/rooms/new">
            <Plus aria-hidden="true" /> Add room
          </Link>
        )}
      </PageTitle>
      <div className="ad-toolbar">
        <SearchBox
          value={filters.search}
          onSearch={(s) => filters.set('search', s)}
          placeholder="Search rooms or locations"
        />
        <p>Hours in Australia/Melbourne</p>
      </div>
      <QueryState pending={rooms.isPending} error={rooms.error} retry={() => void rooms.refetch()}>
        {rooms.data?.items.length ? (
          <div className="ad-room-grid">
            {rooms.data.items.map((room) => (
              <article className="ad-room" key={room.id}>
                <RoomIllustration room={room} />
                <div className="ad-room-body">
                  <div className="ad-section-head">
                    <h2>{room.name}</h2>
                    <Status good={room.active}>{room.active ? 'Active' : 'Inactive'}</Status>
                  </div>
                  <p>{room.location}</p>
                  <div className="ad-room-facts">
                    <span>
                      <Users aria-hidden="true" /> {room.capacity} people
                    </span>
                    <Status good={room.hours_confirmed}>
                      {room.hours_confirmed ? 'Hours confirmed' : 'Hours need review'}
                    </Status>
                  </div>
                  <div className="ad-room-links">
                    <Link to={`/admin/rooms/${room.id}`}>
                      Room details <ArrowUpRight aria-hidden="true" />
                    </Link>
                    <Link to={`/admin/schedules/${room.id}`}>
                      {schedules ? 'Edit schedule' : 'Opening hours'}{' '}
                      <ArrowUpRight aria-hidden="true" />
                    </Link>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty>No rooms match this search.</Empty>
        )}
        {rooms.data && (
          <Pagination
            total={rooms.data.total}
            offset={filters.offset}
            onPage={(o) => filters.set('offset', String(o))}
          />
        )}
      </QueryState>
    </section>
  );
}
export function RoomEditPage() {
  const { roomId = '' } = useParams();
  const room = useAdminQuery(
    ['room', roomId],
    (signal) => adminApi.room(roomId, signal),
    false,
    false,
  );
  return (
    <QueryState pending={room.isPending} error={room.error} retry={() => void room.refetch()}>
      {room.data && <RoomForm initial={room.data} key={room.data.id} />}
    </QueryState>
  );
}
export function RoomForm({ initial: seed }: { initial?: Room }) {
  const [initial] = useState(seed);
  const navigate = useNavigate();
  const session = useAccountSession();
  const [name, setName] = useState(initial?.name ?? '');
  const [location, setLocation] = useState(initial?.location ?? '');
  const [capacity, setCapacity] = useState(String(initial?.capacity ?? 4));
  const [active, setActive] = useState(initial?.active ?? false);
  const [reason, setReason] = useState('');
  const [review, setReview] = useState<{ body: RoomCreate | RoomUpdate; impact?: Impact } | null>(
    null,
  );
  const preview = useMutation({
    mutationFn: async (body: RoomUpdate) => ({
      body,
      impact: await adminApi.impact(initial!.id, body, session.data?.csrf_token ?? ''),
    }),
    onSuccess: setReview,
  });
  const submit = () => {
    const body = { name, location, capacity: Number(capacity), reason };
    if (initial) preview.mutate({ ...body, kind: 'room', active, revision: initial.revision });
    else setReview({ body });
  };
  return (
    <section>
      <Link className="ad-back" to="/admin/rooms">
        ← All rooms
      </Link>
      <PageTitle
        title={initial ? `Edit ${initial.name}` : 'Add a room'}
        description="A good space starts with the details."
      />
      <div className="ad-editor-layout">
        <form
          className="ad-panel ad-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label className="ad-field">
            Room name
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="ad-field">
            Location
            <input
              required
              maxLength={200}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Building and floor"
            />
          </label>
          <label className="ad-field">
            Capacity
            <input
              required
              type="number"
              min={1}
              max={1000}
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
            />
          </label>
          {initial && (
            <label className="ad-check">
              <input
                type="checkbox"
                checked={active}
                disabled={!initial.hours_confirmed && !initial.active}
                onChange={(e) => setActive(e.target.checked)}
              />{' '}
              Active and visible for booking
            </label>
          )}
          <ReasonField value={reason} onChange={setReason} />
          <ErrorNotice error={preview.error} />
          {preview.error && (
            <p>
              <Link reloadDocument to={`/admin/rooms/${initial?.id}`}>
                Reload current room details
              </Link>{' '}
              before trying again. Unsaved changes will be discarded.
            </p>
          )}
          <div className="ad-actions">
            <Link to="/admin/rooms">Cancel</Link>
            <Button type="submit" variant="primary" disabled={preview.isPending}>
              {preview.isPending
                ? 'Checking impact…'
                : initial
                  ? 'Preview change'
                  : 'Review new room'}
            </Button>
          </div>
        </form>
        <aside className="ad-panel ad-note">
          <span className="ad-eyebrow">Before it goes live</span>
          <h2>Ready when you are.</h2>
          <p>New rooms begin inactive. Confirm the opening hours, then activate the room.</p>
          <p>
            Changes that affect existing bookings are blocked. Resolve those bookings explicitly
            before changing availability.
          </p>
          {initial && (
            <Link to={`/admin/schedules/${initial.id}`}>Manage this room’s schedule →</Link>
          )}
        </aside>
      </div>
      {review &&
        (!review.impact?.affected_count ? (
          <ConfirmAction
            title={initial ? 'Save room changes?' : 'Create this room?'}
            intent={{
              action: initial ? 'room.update' : 'room.create',
              target: initial?.id,
              payload: review.body,
            }}
            onClose={() => setReview(null)}
            onSuccess={() => {
              void navigate('/admin/rooms');
            }}
            action={(csrf, key) =>
              initial
                ? adminApi.updateRoom(initial.id, review.body as RoomUpdate, csrf, key)
                : adminApi.createRoom(review.body, csrf, key)
            }
          >
            <p>
              <strong>{review.body.name}</strong> · {review.body.location} · {review.body.capacity}{' '}
              people
            </p>
            <p>
              {initial
                ? `${active ? 'Active' : 'Inactive'}. No existing bookings are affected by this preview.`
                : 'The room will be created inactive with unconfirmed hours.'}
            </p>
            <p>Reason: {review.body.reason}</p>
          </ConfirmAction>
        ) : (
          <div className="ad-error" role="alert">
            <h2>{review.impact.affected_count} booking(s) affected</h2>
            <p>This change cannot be saved. Review affected bookings before changing the room.</p>
            <Link to={`/admin/bookings?room_id=${initial?.id}`}>View bookings</Link>
            <Button onClick={() => setReview(null)}>Keep editing</Button>
          </div>
        ))}
    </section>
  );
}
