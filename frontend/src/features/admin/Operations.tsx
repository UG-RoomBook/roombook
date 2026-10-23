import { useAdminQuery, useFilters, formatTime } from './hooks';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CalendarDays, DoorOpen, Users, ArrowUpRight, Clock3 } from 'lucide-react';
import { campusToday } from '@/shared/dates';
import { PageTitle } from '@/shared/ui/PageTitle';
import { Button } from '@/shared/ui/Button';
import type { AdminBookingsData } from '@/shared/api/generated/types.gen';
import { adminApi, type Activity, type Booking, type User } from './api';
import {
  ConfirmAction,
  Dialog,
  Empty,
  Pagination,
  QueryState,
  ReasonField,
  SearchBox,
  Status,
} from './shared';

function BookingRows({
  items,
  onSelect,
}: {
  items: Booking[];
  onSelect?: (booking: Booking) => void;
}) {
  if (!items.length) return <Empty>No bookings in this view.</Empty>;
  return (
    <div className="ad-table-wrap">
      <table className="ad-table">
        <thead>
          <tr>
            <th>Room & member</th>
            <th>When</th>
            <th>Status</th>
            <th>
              <span className="ad-sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.id}>
              <td data-label="Room & member">
                <strong>{b.room_name}</strong>
                <span className="ad-muted">{b.owner_label}</span>
              </td>
              <td data-label="When">
                {formatTime(b.starts_at)}
                <span className="ad-muted">
                  Until {formatTime(b.ends_at, { day: undefined, month: undefined })}
                </span>
              </td>
              <td data-label="Status">
                <Status good={b.status === 'Ongoing'}>{b.status}</Status>
              </td>
              <td>
                {onSelect ? (
                  <Button onClick={() => onSelect(b)}>View booking</Button>
                ) : (
                  <Link
                    to={`/admin/bookings?search=${b.id}`}
                    aria-label={`View booking for ${b.room_name}`}
                  >
                    View <ArrowUpRight aria-hidden="true" />
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function ActivityRows({ items }: { items: Activity[] }) {
  if (!items.length) return <Empty>No activity in this view.</Empty>;
  return (
    <ol className="ad-activity">
      {items.map((event) => (
        <li key={event.id}>
          <span className="ad-activity-dot" aria-hidden="true" />
          <div>
            <strong>{event.action.split('.').join(' ')}</strong>
            <p>{event.actor_label}</p>
            {typeof event.details.reason === 'string' && <p>{event.details.reason}</p>}
            <time dateTime={event.occurred_at}>{formatTime(event.occurred_at)}</time>
            <details>
              <summary>View record</summary>
              <dl>
                <dt>Target</dt>
                <dd>{event.target_id || '—'}</dd>
                <dt>Actor ID</dt>
                <dd>{event.actor_user_id || 'Operator'}</dd>
              </dl>
              <pre>{JSON.stringify(event.details, null, 2)}</pre>
            </details>
          </div>
        </li>
      ))}
    </ol>
  );
}
export function OverviewPage() {
  const overview = useAdminQuery(['overview'], adminApi.overview, true);
  const data = overview.data;
  return (
    <section>
      <div className="ad-eyebrow">RoomBook administration</div>
      <PageTitle title="A little room to manage." description="Your campus spaces, at a glance." />
      <QueryState
        pending={overview.isPending}
        error={overview.error}
        retry={() => void overview.refetch()}
      >
        {data && (
          <>
            <div className="ad-metrics">
              {[
                {
                  label: 'Bookings today',
                  value: data.bookings_today,
                  Icon: CalendarDays,
                  to: `/admin/bookings?day=${campusToday(data.generated_at)}`,
                },
                {
                  label: 'Active rooms',
                  value: data.active_rooms,
                  Icon: DoorOpen,
                  to: '/admin/rooms',
                },
                {
                  label: 'Active users',
                  value: data.active_users,
                  Icon: Users,
                  to: '/admin/users',
                },
                {
                  label: 'Schedules to confirm',
                  value: data.unconfirmed_rooms,
                  Icon: Clock3,
                  to: '/admin/schedules',
                },
              ].map(({ label, value, Icon, to }) => (
                <Link className="ad-metric" to={to} key={label}>
                  <span>
                    <Icon aria-hidden="true" />
                    {label}
                  </span>
                  <strong>{value.toLocaleString()}</strong>
                  <ArrowUpRight className="ad-metric-arrow" aria-hidden="true" />
                </Link>
              ))}
            </div>
            {!!data.unconfirmed_rooms && (
              <div className="ad-attention">
                <div>
                  <strong>A few spaces need your attention.</strong>
                  <p>
                    {data.unconfirmed_rooms} room(s) need confirmed opening hours before they can
                    take bookings.
                  </p>
                </div>
                <Link to="/admin/schedules">
                  Review schedules <ArrowUpRight aria-hidden="true" />
                </Link>
              </div>
            )}
            <div className="ad-overview-grid">
              <section className="ad-panel ad-panel-flush">
                <div className="ad-section-head ad-panel-heading">
                  <div>
                    <span className="ad-eyebrow">On the calendar</span>
                    <h2>Today’s agenda</h2>
                  </div>
                  <Link to="/admin/bookings">All bookings →</Link>
                </div>
                <BookingRows items={data.agenda} />
              </section>
              <section className="ad-panel">
                <div className="ad-section-head">
                  <h2>Recent activity</h2>
                  <Link to="/admin/activity" aria-label="All activity">
                    <ArrowUpRight aria-hidden="true" />
                  </Link>
                </div>
                <ActivityRows items={data.recent_activity} />
              </section>
            </div>
            <p className="ad-freshness">
              Updated {formatTime(data.generated_at)} · Refreshes every 30 seconds while this page
              is visible.
            </p>
          </>
        )}
      </QueryState>
    </section>
  );
}
export function BookingsPage() {
  const filters = useFilters();
  const rawStatus = filters.params.get('status') || 'all';
  const status = (
    ['all', 'upcoming', 'ongoing', 'completed', 'cancelled'].includes(rawStatus) ? rawStatus : 'all'
  ) as NonNullable<AdminBookingsData['query']>['status'];
  const query = {
    limit: 20,
    offset: filters.offset,
    status,
    search: filters.search,
    ...(filters.params.get('room_id') ? { room_id: filters.params.get('room_id')! } : {}),
    ...(filters.params.get('day') ? { day: filters.params.get('day')! } : {}),
  };
  const bookings = useAdminQuery(
    ['bookings', query],
    (signal) => adminApi.bookings(query, signal),
    true,
  );
  const [selected, setSelected] = useState<Booking | null>(null);
  const [reason, setReason] = useState('');
  const [confirm, setConfirm] = useState(false);
  return (
    <section>
      <PageTitle
        title="Bookings"
        description="See what’s coming up. Keep every change accountable."
      />
      <div className="ad-toolbar">
        <SearchBox
          value={filters.search}
          onSearch={(s) => filters.set('search', s)}
          placeholder="Search room, member or booking ID"
        />
        <label>
          Status
          <select value={status} onChange={(e) => filters.set('status', e.target.value)}>
            {['all', 'upcoming', 'ongoing', 'completed', 'cancelled'].map((s) => (
              <option key={s} value={s}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Date
          <input
            type="date"
            value={filters.params.get('day') || ''}
            onChange={(e) => filters.set('day', e.target.value)}
          />
        </label>
        {query.room_id && (
          <Button onClick={() => filters.set('room_id', '')}>Clear room filter</Button>
        )}
      </div>
      <QueryState
        pending={bookings.isPending}
        error={bookings.error}
        retry={() => void bookings.refetch()}
      >
        <div className="ad-panel ad-panel-flush">
          <BookingRows
            items={bookings.data?.items || []}
            onSelect={(b) => {
              setSelected(b);
              setReason('');
            }}
          />
        </div>
        {bookings.data && (
          <>
            <Pagination
              total={bookings.data.total}
              offset={filters.offset}
              onPage={(o) => filters.set('offset', String(o))}
            />
            <p className="ad-freshness">
              Updated {formatTime(bookings.data.generated_at)} · Refreshes every 30 seconds.
            </p>
          </>
        )}
      </QueryState>
      {selected &&
        (confirm ? (
          <ConfirmAction
            title="Cancel this booking?"
            intent={{ action: 'booking.cancel', target: selected.id, payload: { reason } }}
            confirmLabel="Cancel booking"
            onClose={() => setConfirm(false)}
            onSuccess={() => {
              setSelected(null);
              setConfirm(false);
            }}
            action={(csrf, key) => adminApi.cancel(selected.id, reason, csrf, key)}
          >
            <p>
              <strong>{selected.room_name}</strong> · {selected.owner_label}
            </p>
            <p>
              {formatTime(selected.starts_at)} – {formatTime(selected.ends_at)}
            </p>
            <p>Reason: {reason}</p>
            <p>
              The room becomes available again. This cancellation is recorded in activity history.
            </p>
          </ConfirmAction>
        ) : (
          <Dialog title={selected.room_name} onClose={() => setSelected(null)}>
            <dl className="ad-details">
              <dt>Member</dt>
              <dd>{selected.owner_label}</dd>
              <dt>Booking ID</dt>
              <dd>{selected.id}</dd>
              <dt>Start</dt>
              <dd>{formatTime(selected.starts_at)}</dd>
              <dt>End</dt>
              <dd>{formatTime(selected.ends_at)}</dd>
              <dt>Status</dt>
              <dd>{selected.status}</dd>
            </dl>
            {['Upcoming', 'Ongoing'].includes(selected.status) && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  setConfirm(true);
                }}
              >
                <ReasonField value={reason} onChange={setReason} />
                <Button type="submit" variant="primary">
                  Review cancellation
                </Button>
              </form>
            )}
          </Dialog>
        ))}
    </section>
  );
}
export function UsersPage() {
  const filters = useFilters();
  const query = { limit: 20, offset: filters.offset, search: filters.search };
  const users = useAdminQuery(['users', query], (signal) => adminApi.users(query, signal));
  const [selected, setSelected] = useState<User | null>(null);
  return (
    <section>
      <PageTitle title="Users" description="The right access for the people who use your spaces." />
      <div className="ad-toolbar">
        <SearchBox
          value={filters.search}
          onSearch={(s) => filters.set('search', s)}
          placeholder="Search verified email or user ID"
        />
        <p>Only registered application accounts appear here.</p>
      </div>
      <QueryState pending={users.isPending} error={users.error} retry={() => void users.refetch()}>
        <div className="ad-panel ad-panel-flush">
          {users.data?.items.length ? (
            <table className="ad-table">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>
                    <span className="ad-sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((user) => (
                  <tr key={user.id}>
                    <td data-label="Account">
                      <strong>{user.verified_email || 'Email not yet refreshed'}</strong>
                      <span className="ad-muted ad-id">{user.id}</span>
                    </td>
                    <td data-label="Role">{user.role}</td>
                    <td data-label="Status">
                      <Status good={user.is_active}>
                        {user.is_active ? 'Active' : 'Suspended'}
                      </Status>
                    </td>
                    <td>
                      <Button onClick={() => setSelected(user)}>Manage access</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No accounts match this search.</Empty>
          )}
        </div>
        {users.data && (
          <Pagination
            total={users.data.total}
            offset={filters.offset}
            onPage={(o) => filters.set('offset', String(o))}
          />
        )}
      </QueryState>
      {selected && <UserAccess user={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
function UserAccess({ user, onClose }: { user: User; onClose: () => void }) {
  const [role, setRole] = useState(user.role);
  const [active, setActive] = useState(user.is_active);
  const [reason, setReason] = useState('');
  const [confirm, setConfirm] = useState(false);
  const body = { revision: user.revision, role, is_active: active, reason };
  if (confirm)
    return (
      <ConfirmAction
        title="Change account access?"
        intent={{ action: 'user.update', target: user.id, payload: body }}
        action={(csrf, key) => adminApi.updateUser(user.id, body, csrf, key)}
        onClose={() => setConfirm(false)}
        onSuccess={onClose}
      >
        <p>{user.verified_email || user.id}</p>
        <p>
          {user.role} → <strong>{role}</strong> · {active ? 'Active' : 'Suspended'}
        </p>
        <p>
          Existing sessions will be signed out. Existing bookings are preserved. Admins must verify
          an authenticator to enter this workspace.
        </p>
        <p>Reason: {reason}</p>
      </ConfirmAction>
    );
  return (
    <Dialog title="Manage access" onClose={onClose}>
      <p>{user.verified_email || user.id}</p>
      <p className="ad-hint">
        Email last checked:{' '}
        {user.email_checked_at ? formatTime(user.email_checked_at) : 'Not yet available'}
      </p>
      <form
        className="ad-form"
        onSubmit={(e) => {
          e.preventDefault();
          setConfirm(true);
        }}
      >
        <label className="ad-field">
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as User['role'])}>
            <option>Member</option>
            <option>Admin</option>
          </select>
        </label>
        <label className="ad-check">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />{' '}
          Account active
        </label>
        <ReasonField value={reason} onChange={setReason} />
        <Button
          variant="primary"
          type="submit"
          disabled={role === user.role && active === user.is_active}
        >
          Review access change
        </Button>
      </form>
    </Dialog>
  );
}
export function ActivityPage() {
  const filters = useFilters();
  const query = {
    limit: 20,
    offset: filters.offset,
    action: filters.search,
    ...(filters.params.get('target') ? { target: filters.params.get('target')! } : {}),
    ...(filters.params.get('actor') ? { actor: filters.params.get('actor')! } : {}),
  };
  const activity = useAdminQuery(['activity', query], (signal) => adminApi.activity(query, signal));
  return (
    <section>
      <PageTitle title="Activity" description="A clear record of who changed what, and why." />
      <div className="ad-toolbar">
        <SearchBox
          value={filters.search}
          onSearch={(s) => filters.set('search', s)}
          placeholder="Filter by action, e.g. room or user"
        />
        <label>
          Target ID
          <input
            value={filters.params.get('target') || ''}
            onChange={(e) => filters.set('target', e.target.value)}
            placeholder="Optional UUID"
          />
        </label>
        <label>
          Actor ID
          <input
            value={filters.params.get('actor') || ''}
            onChange={(e) => filters.set('actor', e.target.value)}
            placeholder="Optional UUID"
          />
        </label>
      </div>
      <QueryState
        pending={activity.isPending}
        error={activity.error}
        retry={() => void activity.refetch()}
      >
        <div className="ad-panel">
          <ActivityRows items={activity.data?.items || []} />
        </div>
        {activity.data && (
          <Pagination
            total={activity.data.total}
            offset={filters.offset}
            onPage={(o) => filters.set('offset', String(o))}
          />
        )}
      </QueryState>
    </section>
  );
}
