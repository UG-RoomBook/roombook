import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AccountNavigation, AccountPage } from './AccountPage';
import { safeReturnTo } from './session';
import { SESSION_KEY } from './api';

const session = {
  user: { id: '00000000-0000-4000-8000-000000000001', role: 'Member' },
  aal: 'aal1',
  purpose: 'standard',
  expires_at: '2026-10-20T00:00:00Z',
  csrf_token: 'synthetic-csrf',
};
let signedIn = false;
const server = setupServer(
  http.get('*/api/v1/auth/session', () =>
    signedIn
      ? HttpResponse.json(session)
      : HttpResponse.json(
          { error: { message: 'Sign in to continue.', code: 'AUTH_REQUIRED' } },
          { status: 401 },
        ),
  ),
  http.post('*/api/v1/auth/login', () => {
    signedIn = true;
    return HttpResponse.json(session);
  }),
  http.post('*/api/v1/auth/register', () =>
    HttpResponse.json({ message: 'Check your email to verify your account.' }),
  ),
  http.post('*/api/v1/auth/recover', () =>
    HttpResponse.json({ message: 'If eligible, a recovery email has been sent.' }),
  ),
  http.post('*/api/v1/auth/resend', () =>
    HttpResponse.json({ message: 'Check your email for a new link.' }),
  ),
  http.post('*/api/v1/auth/logout', () => {
    signedIn = false;
    return new HttpResponse(null, { status: 204 });
  }),
);
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());
beforeEach(() => {
  signedIn = false;
});

function setup(path: string) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  cache.setQueryData(['bookings'], ['previous-account-private-data']);
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[path]}>
        <AccountNavigation />
        <Routes>
          <Route path="/account/*" element={<AccountPage />} />
          <Route path="/" element={<h1>Rooms destination</h1>} />
          <Route path="/review" element={<h1>Booking destination</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return cache;
}

function fill(email = 'member@example.com', password = 'synthetic-password-123') {
  if (screen.queryByLabelText('Email address'))
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: email } });
  if (screen.queryByLabelText('Password'))
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } });
}

describe('account forms', () => {
  it('signs in through the account client, clears private caches and preserves a safe destination', async () => {
    const cache = setup('/account/login?next=%2Freview%3Froom_id%3Dstudio');
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Booking destination' })).toBeInTheDocument();
    expect(cache.getQueryData(['bookings'])).toBeUndefined();
    expect(screen.getByRole('link', { name: 'Account' })).toBeInTheDocument();
  });
  it('validates email and new password inline without suppressing password managers', async () => {
    setup('/account/register');
    fill('bad-email', 'short');
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password');
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }));
    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument();
    expect(screen.getByText('Use at least 12 characters.')).toBeInTheDocument();
  });
  it.each([
    ['register', 'Create an account', 'Check your email to verify your account.'],
    ['recover', 'Recover your account', 'If eligible, a recovery email has been sent.'],
    ['resend', 'Resend verification', 'Check your email for a new link.'],
  ])('shows generic %s feedback', async (mode, label, message) => {
    setup(`/account/${mode}`);
    fill();
    fireEvent.click(screen.getByRole('button', { name: label }));
    expect(await screen.findByText(message)).toHaveAttribute('role', 'status');
    expect(screen.getByRole('heading', { name: label })).toBeInTheDocument();
  });
  it('shows a safe failure and retains the entered email', async () => {
    server.use(
      http.post('*/api/v1/auth/login', () =>
        HttpResponse.json(
          {
            error: {
              message: 'Check your credentials and verify your email.',
              code: 'SIGN_IN_REJECTED',
            },
          },
          { status: 401 },
        ),
      ),
    );
    setup('/account/login');
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Check your credentials');
    expect(screen.getByLabelText('Email address')).toHaveValue('member@example.com');
  });
  it('disables repeated submission while the request is pending', async () => {
    let finish: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    let calls = 0;
    server.use(
      http.post('*/api/v1/auth/login', async () => {
        calls++;
        await gate;
        return HttpResponse.json(session);
      }),
    );
    setup('/account/login');
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: 'Working…' }));
    expect(calls).toBe(1);
    finish?.();
    expect(await screen.findByText('Rooms destination')).toBeInTheDocument();
  });
  it('logs out with CSRF and removes private query data', async () => {
    signedIn = true;
    const cache = setup('/account');
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(cache.getQueryData(['bookings'])).toBeUndefined();
  });
  it('clears private data when another tab changes accounts', async () => {
    const cache = setup('/account/login');
    fireEvent(
      window,
      new StorageEvent('storage', {
        key: 'roombook.account.changed',
        newValue: 'synthetic-change',
      }),
    );
    await waitFor(() => expect(cache.getQueryData(['bookings'])).toBeUndefined());
  });
  it('requires a recovery session before enabling the password form', async () => {
    server.use(
      http.get('*/api/v1/auth/recovery-session', () =>
        HttpResponse.json(
          { error: { code: 'AUTH_REQUIRED', message: 'Request a new recovery link.' } },
          { status: 401 },
        ),
      ),
    );
    setup('/account/reset');
    expect(await screen.findByText('Request a new recovery link.')).toHaveAttribute(
      'role',
      'alert',
    );
    expect(screen.getByRole('button', { name: 'Save new password' })).toBeDisabled();
  });
  it('submits the new password with the recovery CSRF then returns to sign in', async () => {
    server.use(
      http.get('*/api/v1/auth/recovery-session', () =>
        HttpResponse.json({ csrf_token: 'recovery-csrf' }),
      ),
      http.post('*/api/v1/auth/reset-password', ({ request }) =>
        request.headers.get('X-CSRF-Token') === 'recovery-csrf'
          ? HttpResponse.json({ message: 'Password changed. Sign in again.' })
          : new HttpResponse(null, { status: 403 }),
      ),
    );
    setup('/account/reset');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Save new password' })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'synthetic-password-123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save new password' }));
    expect(await screen.findByText('Password changed. Sign in again.')).toHaveAttribute(
      'role',
      'status',
    );
  });
  it('reports an unusable link on a clean account URL', () => {
    setup('/account/login?notice=link-error');
    expect(screen.getByRole('alert')).toHaveTextContent('Request a new link');
  });
});

describe('safe post-login destinations', () => {
  it.each([
    'https://evil.example',
    '//evil.example',
    '/\\evil.example',
    '/%2f%2fevil.example',
    '/account/reset',
    '/review\nLocation:evil',
  ])('rejects %s', (value) => expect(safeReturnTo(value)).toBe('/'));
  it('retains room selection filters', () =>
    expect(safeReturnTo('/review?room_id=studio&date=2026-10-20')).toBe(
      '/review?room_id=studio&date=2026-10-20',
    ));
});

it('removes prior private bookings when revalidation reports an expired session', async () => {
  signedIn = true;
  const cache = setup('/account');
  expect(await screen.findByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  signedIn = false;
  await cache.invalidateQueries({ queryKey: SESSION_KEY });
  await waitFor(() => expect(cache.getQueryData(['bookings'])).toBeUndefined());
  expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
});
