import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { UserRound } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/shared/ui/Button';
import { accountApi, SESSION_KEY } from './api';
import { safeReturnTo, useAccountSession } from './session';
import './accounts.css';

export function AccountNavigation() {
  const session = useAccountSession();
  const cache = useQueryClient();
  const location = useLocation();
  const previousUser = useRef<string | undefined>(undefined);
  useEffect(() => {
    const current = session.isError ? undefined : session.data?.user.id;
    if (previousUser.current && current !== previousUser.current) {
      const privateQueries = { queryKey: ['bookings'] };
      void cache.cancelQueries(privateQueries).then(() => cache.removeQueries(privateQueries));
    }
    if (!session.isPending) previousUser.current = current;
  }, [cache, session.data, session.isError, session.isPending]);
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === 'roombook.account.changed') {
        void cache.cancelQueries().then(() => cache.clear());
      }
    };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, [cache]);
  return (
    <Link
      to="/account"
      aria-current={location.pathname.startsWith('/account') ? 'page' : undefined}
    >
      <UserRound aria-hidden="true" />
      {session.data && !session.isError ? 'Account' : 'Sign in'}
    </Link>
  );
}

const titles: Record<string, string> = {
  login: 'Sign in',
  register: 'Create an account',
  recover: 'Recover your account',
  resend: 'Resend verification',
  reset: 'Choose a new password',
  email: 'Change your email',
};

function accountChanged() {
  try {
    localStorage.setItem('roombook.account.changed', crypto.randomUUID());
  } catch {
    /* Storage may be unavailable; normal session revalidation remains active. */
  }
}

function AccountForm({ mode }: { mode: string }) {
  const queryClient = useQueryClient();
  const session = useAccountSession();
  const recovery = useQuery({
    queryKey: ['identity', 'recovery'],
    queryFn: ({ signal }) => accountApi.recovery(signal),
    enabled: mode === 'reset',
    retry: false,
    staleTime: 0,
  });
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [notice, setNotice] = useState('');
  const needsPassword = ['login', 'register', 'reset'].includes(mode);
  const needsEmail = mode !== 'reset';
  const {
    register,
    handleSubmit,
    resetField,
    formState: { errors },
  } = useForm<{ email: string; password: string }>();
  const clearPrivate = async () => {
    await queryClient.cancelQueries();
    queryClient.clear();
    accountChanged();
  };
  const mutation = useMutation({
    mutationFn: async (values: { email: string; password: string }) => {
      if (mode === 'login') {
        const result = await accountApi.login(values);
        await clearPrivate();
        queryClient.setQueryData(SESSION_KEY, result);
        await navigate(safeReturnTo(params.get('next')), { replace: true });
        return;
      }
      const result =
        mode === 'register'
          ? await accountApi.register(values)
          : mode === 'recover'
            ? await accountApi.recover(values.email)
            : mode === 'resend'
              ? await accountApi.resend(values.email)
              : mode === 'reset'
                ? await accountApi.reset(values.password, recovery.data?.csrf_token ?? '')
                : await accountApi.email(values.email, session.data?.csrf_token ?? '');
      resetField('password');
      if (mode === 'reset' || mode === 'email') {
        await clearPrivate();
        await navigate('/account/login', { replace: true, state: { notice: result.message } });
      } else setNotice(result.message);
    },
  });
  const notices: Record<string, string> = {
    verified: 'Your email link was confirmed. Sign in to continue.',
    'email-change':
      'Email confirmation received. If both addresses are confirmed, sign in with your new email.',
    'link-error': 'This link could not be verified. Request a new link and try again.',
  };
  const routeState: unknown = location.state;
  const routeNotice =
    routeState &&
    typeof routeState === 'object' &&
    'notice' in routeState &&
    typeof routeState.notice === 'string'
      ? routeState.notice
      : '';
  const message = notice || routeNotice || notices[params.get('notice') ?? ''];
  const restrictedError =
    mode === 'reset' ? recovery.error : mode === 'email' ? session.error : null;
  const unavailable =
    mode === 'reset' ? !recovery.data : mode === 'email' ? !session.data || session.isError : false;
  return (
    <div className="sw-account-panel">
      {message && (
        <p
          role={params.get('notice') === 'link-error' ? 'alert' : 'status'}
          className="sw-account-message"
        >
          {message}
        </p>
      )}
      {mode === 'register' && (
        <p>Verify your email before signing in. Use a password with at least 12 characters.</p>
      )}
      {mode === 'reset' && <p>This recovery session only allows you to choose a new password.</p>}
      {mode === 'email' && (
        <p>Confirm the change from your email inboxes. You will be signed out.</p>
      )}
      {restrictedError && <p role="alert">{restrictedError.message}</p>}
      <form
        noValidate
        onSubmit={(event) => void handleSubmit((values) => mutation.mutate(values))(event)}
        aria-busy={mutation.isPending}
      >
        {needsEmail && (
          <label htmlFor="account-email">
            {mode === 'email' ? 'New email address' : 'Email address'}
            <input
              id="account-email"
              type="email"
              autoComplete={mode === 'email' ? 'email' : 'username'}
              maxLength={320}
              aria-invalid={!!errors.email}
              aria-describedby={errors.email ? 'account-email-error' : undefined}
              {...register('email', {
                required: 'Enter your email address.',
                pattern: {
                  value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
                  message: 'Enter a valid email address.',
                },
              })}
            />
            {errors.email && (
              <span id="account-email-error" role="alert">
                {errors.email.message}
              </span>
            )}
          </label>
        )}
        {needsPassword && (
          <label htmlFor="account-password">
            {mode === 'reset' ? 'New password' : 'Password'}
            <input
              id="account-password"
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              maxLength={128}
              aria-invalid={!!errors.password}
              aria-describedby={errors.password ? 'account-password-error' : undefined}
              {...register('password', {
                required: 'Enter a password.',
                minLength: {
                  value: mode === 'login' ? 1 : 12,
                  message: 'Use at least 12 characters.',
                },
              })}
            />
            {errors.password && (
              <span id="account-password-error" role="alert">
                {errors.password.message}
              </span>
            )}
          </label>
        )}
        {mutation.error && <p role="alert">{mutation.error.message}</p>}
        <Button type="submit" variant="primary" disabled={mutation.isPending || unavailable}>
          {mutation.isPending
            ? 'Working…'
            : mode === 'reset'
              ? 'Save new password'
              : mode === 'email'
                ? 'Request email change'
                : titles[mode]}
        </Button>
      </form>
      <nav aria-label="Account options" className="sw-account-links">
        {Object.entries(titles)
          .filter(([key]) => !['reset', 'email', mode].includes(key))
          .map(([key, title]) => (
            <Link key={key} to={`/account/${key}`}>
              {title}
            </Link>
          ))}
      </nav>
    </div>
  );
}

function AccountSummary() {
  const session = useAccountSession();
  const client = useQueryClient();
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: async () => {
      if (!session.data) return;
      await accountApi.logout(session.data.csrf_token);
      await client.cancelQueries();
      client.clear();
      accountChanged();
      await navigate('/account/login', { replace: true });
    },
  });
  if (session.isPending) return <p role="status">Checking your session…</p>;
  if (!session.data || session.isError)
    return (
      <div className="sw-account-panel">
        {session.error && <p role="alert">{session.error.message}</p>}
        <p>Sign in to manage your bookings. You can browse rooms without an account.</p>
        <Link to="/account/login">Sign in</Link>
        <Link to="/account/register">Create an account</Link>
      </div>
    );
  return (
    <div className="sw-account-panel">
      <p role="status">You are signed in as a {session.data.user.role.toLowerCase()}.</p>
      <Link to="/account/email">Change email address</Link>
      {logout.error && <p role="alert">{logout.error.message}</p>}
      <Button disabled={logout.isPending} onClick={() => logout.mutate()}>
        {logout.isPending ? 'Signing out…' : 'Sign out'}
      </Button>
    </div>
  );
}

export function AccountPage() {
  const location = useLocation();
  const candidate = location.pathname.split('/')[2] ?? '';
  const mode = Object.hasOwn(titles, candidate) ? candidate : '';
  return (
    <section className="sw-account">
      <h1 tabIndex={-1}>{titles[mode] ?? 'Your account'}</h1>
      {mode ? <AccountForm mode={mode} key={mode + location.key} /> : <AccountSummary />}
    </section>
  );
}
