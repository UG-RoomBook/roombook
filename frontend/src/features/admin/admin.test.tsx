import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AdminNavigation, AdminLink } from './Admin';
import { AdminPage } from './AdminPage';
import { MfaPage } from '@/features/accounts/MfaPage';
import { adminApi } from './api';
import { SESSION_KEY } from '@/features/accounts/api';
import { safeReturnTo } from '@/features/accounts/session';

const id = '10000000-0000-4000-8000-000000000001';
const memberId = '20000000-0000-4000-8000-000000000002';
const factorId = '30000000-0000-4000-8000-000000000001';
const adminSession = {
  user: { id, role: 'Admin' },
  aal: 'aal2',
  purpose: 'standard',
  expires_at: '2030-10-23T01:00:00Z',
  csrf_token: 'csrf',
  mfa_verified_at: '2026-10-23T00:00:00Z',
};
let session: typeof adminSession | null;
const room = {
  id,
  name: 'The Studio',
  location: 'Level 2',
  capacity: 4,
  active: true,
  hours_confirmed: true,
  revision: 1,
};
const booking = {
  id,
  room_id: id,
  room_name: 'The Studio',
  owner_id: memberId,
  owner_label: 'student@example.com',
  starts_at: '2026-10-23T00:00:00Z',
  ends_at: '2026-10-23T01:00:00Z',
  created_at: '2026-10-22T00:00:00Z',
  cancelled_at: null,
  status: 'Upcoming',
};
const member = {
  id: memberId,
  verified_email: 'student@example.com',
  email_checked_at: '2026-10-23T00:00:00Z',
  role: 'Member',
  is_active: true,
  revision: 1,
  created_at: '2026-10-22T00:00:00Z',
};
const schedule = {
  room_id: id,
  revision: 1,
  timezone: 'Australia/Melbourne',
  hours_confirmed: true,
  weekly: [{ weekday: 0, start_minute: 540, end_minute: 1020 }],
  exceptions: [],
  closures: [],
};
const activity = {
  id,
  actor_user_id: id,
  actor_label: 'admin@example.com',
  target_id: id,
  action: 'admin.room.updated',
  occurred_at: '2026-10-23T00:00:00Z',
  details: { reason: 'Capacity update', before: { capacity: 2 }, after: { capacity: 4 } },
};
function page<T>(items: T[], total = items.length) {
  return { items, total, limit: 20, offset: 0, generated_at: '2026-10-23T00:00:00Z' };
}
function failure(code: string, status = 409) {
  return HttpResponse.json({ error: { code, message: code } }, { status });
}
const server = setupServer(
  http.get('*/api/v1/auth/session', () =>
    session ? HttpResponse.json(session) : failure('AUTH_REQUIRED', 401),
  ),
  http.get('*/api/v1/admin/overview', () =>
    HttpResponse.json({
      generated_at: '2026-10-23T00:00:00Z',
      timezone: 'Australia/Melbourne',
      active_rooms: 2,
      active_users: 8,
      bookings_today: 1,
      unconfirmed_rooms: 1,
      agenda: [booking],
      recent_activity: [activity],
    }),
  ),
  http.get('*/api/v1/admin/rooms', () => HttpResponse.json(page([room]))),
  http.get('*/api/v1/admin/rooms/:id', () => HttpResponse.json(room)),
  http.post('*/api/v1/admin/rooms', async ({ request }) =>
    HttpResponse.json(
      { ...room, ...((await request.json()) as object), active: false, hours_confirmed: false },
      { status: 201 },
    ),
  ),
  http.put('*/api/v1/admin/rooms/:id', async ({ request }) =>
    HttpResponse.json({ ...room, ...((await request.json()) as object), revision: 2 }),
  ),
  http.get('*/api/v1/admin/rooms/:id/schedule', () => HttpResponse.json(schedule)),
  http.put('*/api/v1/admin/rooms/:id/schedule', async ({ request }) =>
    HttpResponse.json({ ...schedule, ...((await request.json()) as object), revision: 2 }),
  ),
  http.post('*/api/v1/admin/rooms/:id/impact', () =>
    HttpResponse.json({
      revision: 1,
      affected_count: 0,
      affected_bookings: [],
      generated_at: '2026-10-23T00:00:00Z',
    }),
  ),
  http.get('*/api/v1/admin/bookings', () => HttpResponse.json(page([booking]))),
  http.get('*/api/v1/admin/bookings/:id', () => HttpResponse.json(booking)),
  http.post('*/api/v1/admin/bookings/:id/cancel', () =>
    HttpResponse.json({ ...booking, status: 'Cancelled', cancelled_at: '2026-10-23T00:00:00Z' }),
  ),
  http.get('*/api/v1/admin/users', () => HttpResponse.json(page([member]))),
  http.get('*/api/v1/admin/users/:id', () => HttpResponse.json(member)),
  http.put('*/api/v1/admin/users/:id', async ({ request }) =>
    HttpResponse.json({ ...member, ...((await request.json()) as object), revision: 2 }),
  ),
  http.get('*/api/v1/admin/activity', () => HttpResponse.json(page([activity]))),
  http.get('*/api/v1/auth/mfa', () =>
    HttpResponse.json({
      factors: [{ id: factorId, friendly_name: 'Phone', factor_type: 'totp', status: 'verified' }],
    }),
  ),
  http.post('*/api/v1/auth/mfa/verify', () => {
    session = { ...adminSession };
    return HttpResponse.json(session);
  }),
);
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
});
afterAll(() => server.close());
afterEach(() => server.resetHandlers());
beforeEach(() => {
  session = structuredClone(adminSession);
});
function setup(path: string) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[path]}>
        <AdminNavigation />
        <AdminLink />
        <Routes>
          <Route path="/admin/*" element={<AdminPage />} />
          <Route path="/account/mfa" element={<MfaPage />} />
          <Route path="/" element={<h1>Rooms destination</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return cache;
}
const change = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

describe('admin workspace', () => {
  it('protects anonymous and member routes and offers safe MFA return', async () => {
    session = null;
    setup('/admin/users');
    expect(await screen.findByRole('heading', { name: 'Sign in to continue' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Sign in' }).at(-1)).toHaveAttribute(
      'href',
      '/account/login?next=%2Fadmin%2Fusers',
    );
    expect(safeReturnTo('/admin/users?search=a')).toBe('/admin/users?search=a');
    expect(safeReturnTo('/admin/../../evil')).toBe('/');
    expect(safeReturnTo('//evil.example')).toBe('/');
  });
  it('does not show admin navigation to a member', async () => {
    session = { ...adminSession, user: { id, role: 'Member' } };
    setup('/admin');
    expect(
      await screen.findByRole('heading', { name: 'Administrator access required' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
  });
  it('requires MFA and preserves the destination', async () => {
    session = { ...adminSession, aal: 'aal1', mfa_verified_at: '' };
    setup('/admin/rooms');
    expect(await screen.findByRole('link', { name: 'Verify authenticator' })).toHaveAttribute(
      'href',
      '/account/mfa?next=%2Fadmin%2Frooms',
    );
  });
  it('shows real daily metrics, attention, agenda and readable activity', async () => {
    setup('/admin');
    expect(await screen.findByText('Bookings today')).toBeInTheDocument();
    expect(await screen.findByText('A few spaces need your attention.')).toBeInTheDocument();
    expect(screen.getByText('student@example.com')).toBeInTheDocument();
    fireEvent.click(screen.getByText('View record'));
    expect(screen.getByText('Capacity update')).toBeInTheDocument();
    click('Admin navigation');
    expect(screen.getByRole('button', { name: 'Admin navigation' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    fireEvent.click(screen.getByRole('link', { name: 'Users' }));
    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument();
  });
  it('shows errors and retries without treating missing data as empty', async () => {
    server.use(http.get('*/api/v1/admin/overview', () => failure('Unavailable', 503)));
    setup('/admin');
    expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable');
    server.use(
      http.get('*/api/v1/admin/overview', () =>
        HttpResponse.json({
          generated_at: '2026-10-23T00:00:00Z',
          timezone: 'Australia/Melbourne',
          active_rooms: 0,
          active_users: 0,
          bookings_today: 0,
          unconfirmed_rooms: 0,
          agenda: [],
          recent_activity: [],
        }),
      ),
    );
    click('Try again');
    expect(await screen.findByText('No bookings in this view.')).toBeInTheDocument();
  });
  it('searches rooms, paginates and keeps URL-backed filters', async () => {
    let requestUrl = '';
    server.use(
      http.get('*/api/v1/admin/rooms', ({ request }) => {
        requestUrl = request.url;
        return HttpResponse.json(page([room], 25));
      }),
    );
    setup('/admin/rooms');
    expect(await screen.findByText('Hours confirmed')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Studio' } });
    click('Search');
    await waitFor(() => expect(requestUrl).toContain('search=Studio'));
    click('Next');
    await waitFor(() => expect(requestUrl).toContain('offset=20'));
    click('Previous');
    await waitFor(() => expect(requestUrl).toContain('offset=0'));
  });
  it('creates an inactive room only after confirmation, with a stable key on uncertain retry', async () => {
    let attempts = 0;
    const keys: (string | null)[] = [];
    server.use(
      http.post('*/api/v1/admin/rooms', async ({ request }) => {
        attempts++;
        keys.push(request.headers.get('Idempotency-Key'));
        return attempts === 1
          ? HttpResponse.error()
          : HttpResponse.json(
              { ...room, ...((await request.json()) as object), active: false },
              { status: 201 },
            );
      }),
    );
    setup('/admin/rooms/new');
    await screen.findByLabelText('Room name');
    change('Room name', 'Focus room');
    change('Location', 'Level 3');
    change('Capacity', '6');
    change('Reason for change', 'New space');
    click('Review new room');
    expect(attempts).toBe(0);
    click('Confirm change');
    await screen.findByRole('button', { name: 'Retry same request' });
    expect(screen.getByRole('button', { name: 'Keep editing' })).toBeDisabled();
    click('Retry same request');
    await screen.findByRole('heading', { name: 'Rooms' });
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });
  it('previews edits, rejects affected bookings and keeps inputs', async () => {
    server.use(
      http.post('*/api/v1/admin/rooms/:id/impact', () =>
        HttpResponse.json({
          revision: 1,
          affected_count: 1,
          affected_bookings: [booking],
          generated_at: '2026-10-23T00:00:00Z',
        }),
      ),
    );
    setup(`/admin/rooms/${id}`);
    await screen.findByLabelText('Room name');
    change('Room name', 'Studio revised');
    change('Reason for change', 'Maintenance');
    fireEvent.click(screen.getByLabelText('Active and visible for booking'));
    click('Preview change');
    expect(await screen.findByRole('alert')).toHaveTextContent('1 booking(s) affected');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    click('Keep editing');
    expect(screen.getByLabelText('Room name')).toHaveValue('Studio revised');
  });
  it('saves a previewed room and handles stale revisions', async () => {
    setup(`/admin/rooms/${id}`);
    await screen.findByLabelText('Room name');
    change('Reason for change', 'Capacity update');
    change('Capacity', '8');
    click('Preview change');
    await screen.findByRole('dialog');
    click('Keep editing');
    expect(screen.getByLabelText('Capacity')).toHaveValue(8);
    click('Preview change');
    await screen.findByRole('dialog');
    click('Confirm change');
    await screen.findByRole('heading', { name: 'Rooms' });
  });
  it('edits weekly windows, date overrides and closures then previews and saves', async () => {
    setup(`/admin/schedules/${id}`);
    await screen.findByRole('heading', { name: 'Weekly opening hours' });
    fireEvent.change(screen.getByLabelText('Monday opening 1'), { target: { value: '600' } });
    fireEvent.change(screen.getByLabelText('Monday closing 1'), { target: { value: '1080' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Add hours' })[1]!);
    click('Add date');
    change('Date', '2026-10-26');
    fireEvent.click(
      within(screen.getByRole('group', { name: 'Override 1' })).getByRole('button', {
        name: 'Add hours',
      }),
    );
    click('Add closure');
    change('Starts', '2026-10-27T10:00');
    change('Ends', '2026-10-27T11:00');
    change('Closure reason', 'Maintenance');
    change('Reason for change', 'Facilities approved');
    click('Preview schedule change');
    await screen.findByRole('dialog');
    click('Confirm change');
    await screen.findByRole('heading', { name: 'Schedules' });
  });
  it('does not silently select a DST fold and allows removing draft schedule entries', async () => {
    setup(`/admin/schedules/${id}`);
    await screen.findByRole('heading', { name: 'Weekly opening hours' });
    click('Remove Monday window 1');
    click('Add date');
    click('Remove override 1');
    click('Add closure');
    change('Starts', '2027-04-04T02:15');
    change('Ends', '2027-04-04T03:30');
    change('Closure reason', 'Closure');
    change('Reason for change', 'DST test');
    click('Preview schedule change');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    click('Remove closure 1');
    expect(screen.getByText('No temporary closures.')).toBeInTheDocument();
  });
  it('requires a reason and confirms booking cancellation', async () => {
    setup('/admin/bookings?status=ongoing');
    await screen.findByText('student@example.com');
    click('View booking');
    expect(screen.getByRole('dialog')).toHaveTextContent('Upcoming');
    change('Reason for change', 'Maintenance');
    click('Review cancellation');
    click('Cancel booking');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'cancelled' } });
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-10-23' } });
  });
  it('keeps completed bookings read-only', async () => {
    server.use(
      http.get('*/api/v1/admin/bookings', () =>
        HttpResponse.json(page([{ ...booking, status: 'Completed' }])),
      ),
    );
    setup('/admin/bookings?room_id=' + id);
    await screen.findByText('student@example.com');
    click('View booking');
    expect(screen.queryByRole('button', { name: 'Review cancellation' })).not.toBeInTheDocument();
    click('Close dialog');
    click('Clear room filter');
  });
  it('preserves access changes through MFA and never auto-submits after verification', async () => {
    let saved = 0;
    server.use(
      http.put('*/api/v1/admin/users/:id', () => {
        saved++;
        return saved === 1
          ? failure('MFA_RECENT_REQUIRED', 403)
          : HttpResponse.json({ ...member, is_active: false, revision: 2 });
      }),
    );
    setup('/admin/users');
    await screen.findByText('student@example.com');
    click('Manage access');
    fireEvent.click(screen.getByLabelText('Account active'));
    change('Reason for change', 'Review required');
    click('Review access change');
    click('Confirm change');
    await screen.findByLabelText('Six-digit code');
    change('Six-digit code', '123456');
    click('Verify authenticator');
    await screen.findByText('Authenticator verified. Review the change and save when ready.');
    expect(saved).toBe(1);
    expect(screen.getByText('Reason: Review required')).toBeInTheDocument();
    click('Confirm change');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(saved).toBe(2);
  });
  it('filters and inspects audit records and retrieves direct record APIs', async () => {
    setup('/admin/activity');
    await screen.findByText('Capacity update');
    fireEvent.click(screen.getByText('View record'));
    expect(screen.getAllByText('Actor ID').length).toBe(2);
    change('Target ID', id);
    change('Actor ID', memberId);
    expect((await adminApi.user(memberId)).verified_email).toBe(member.verified_email);
    expect((await adminApi.booking(id)).room_id).toBe(id);
  });
  it('clears private admin data when account identity changes', async () => {
    const cache = setup('/admin');
    await screen.findByText('Bookings today');
    cache.setQueryData(['admin', 'private'], 'secret');
    session = null;
    await cache.invalidateQueries({ queryKey: SESSION_KEY });
    await screen.findByRole('heading', { name: 'Sign in to continue' });
    await waitFor(() => expect(cache.getQueryData(['admin', 'private'])).toBeUndefined());
  });
});

describe('authenticator management', () => {
  it('enrolls a member authenticator, renders its QR as an image, verifies and keeps safe navigation', async () => {
    session = { ...adminSession, user: { id, role: 'Member' }, aal: 'aal1', mfa_verified_at: '' };
    let enrolled = false;
    server.use(
      http.get('*/api/v1/auth/mfa', () =>
        HttpResponse.json({
          factors: enrolled
            ? [{ id: factorId, friendly_name: 'Phone', factor_type: 'totp', status: 'unverified' }]
            : [],
        }),
      ),
      http.post('*/api/v1/auth/mfa/enroll', () => {
        enrolled = true;
        return HttpResponse.json({
          id: factorId,
          secret: 'TESTSETUPKEY',
          qr_code: '<svg xmlns="http://www.w3.org/2000/svg"/>',
        });
      }),
    );
    setup('/account/mfa?next=%2Fadmin');
    await screen.findByLabelText('Authenticator name');
    change('Authenticator name', 'Phone');
    click('Add authenticator');
    expect(
      await screen.findByRole('img', { name: 'Scan with your authenticator app' }),
    ).toHaveAttribute('src', expect.stringContaining('data:image/svg+xml'));
    fireEvent.click(screen.getByText('Enter a setup key instead'));
    expect(screen.getByText('TESTSETUPKEY')).toBeInTheDocument();
    change('Six-digit code', '123456');
    click('Verify authenticator');
    expect(await screen.findByRole('link', { name: 'Continue' })).toHaveAttribute('href', '/admin');
    expect(screen.queryByText('TESTSETUPKEY')).not.toBeInTheDocument();
    expect(sessionStorage.length).toBe(0);
  });
  it('requires a removal reason and prevents removing the last admin factor', async () => {
    setup('/account/mfa');
    await screen.findByLabelText('Reason for removal');
    change('Reason for removal', 'New phone');
    expect(screen.getByRole('button', { name: 'Remove' })).toBeDisabled();
  });
  it('removes a member factor and explains the new sign-in requirement', async () => {
    session = { ...adminSession, user: { id, role: 'Member' } };
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    server.use(
      http.post('*/api/v1/auth/mfa/:id/remove', () => {
        session = null;
        return HttpResponse.json({ message: 'Authenticator removed. Sign in again to continue.' });
      }),
    );
    setup('/account/mfa');
    await screen.findByLabelText('Reason for removal');
    change('Reason for removal', 'Replace device');
    click('Remove');
    expect(
      await screen.findByText('Authenticator removed. Sign in again to continue.'),
    ).toBeInTheDocument();
  });
});
