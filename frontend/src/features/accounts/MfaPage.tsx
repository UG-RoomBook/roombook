import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { z } from 'zod';
import { ShieldCheck, KeyRound } from 'lucide-react';
import { Button } from '@/shared/ui/Button';
import { PageTitle } from '@/shared/ui/PageTitle';
import {
  enrollMfaFactor,
  listMfaFactors,
  removeMfaFactor,
  verifyMfaFactor,
} from '@/shared/api/generated/sdk.gen';
import { accountClient as client, run, sessionSchema, SESSION_KEY } from './api';
import { safeReturnTo, useAccountSession } from './session';
import type { Enrollment } from '@/shared/api/generated/types.gen';
import './accounts.css';

const factorSchema = z.object({
  id: z.uuid(),
  friendly_name: z.string(),
  factor_type: z.literal('totp'),
  status: z.enum(['verified', 'unverified']),
});
const factorsSchema = z.object({ factors: z.array(factorSchema) });
const enrollmentSchema = z.object({ id: z.uuid(), secret: z.string(), qr_code: z.string() });
export function MfaPanel({
  onVerified,
  compact = false,
}: {
  onVerified?: () => void;
  compact?: boolean;
}) {
  const session = useAccountSession();
  const location = useLocation();
  const cache = useQueryClient();
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [selected, setSelected] = useState('');
  const [code, setCode] = useState('');
  const [name, setName] = useState('My authenticator');
  const [reason, setReason] = useState('');
  const [notice, setNotice] = useState('');
  const factors = useQuery({
    queryKey: ['identity', 'mfa', session.data?.user.id],
    queryFn: ({ signal }) =>
      run((s) => listMfaFactors({ client, signal: s, cache: 'no-store' }), factorsSchema, signal),
    enabled: !!session.data,
    retry: false,
  });
  const csrf = { 'X-CSRF-Token': session.data?.csrf_token ?? '' };
  const enroll = useMutation({
    mutationFn: () =>
      run(
        (signal) => enrollMfaFactor({ client, signal, body: { name }, headers: csrf }),
        enrollmentSchema,
      ),
    onSuccess: (result) => {
      setEnrollment(result);
      setSelected(result.id);
      setNotice('Scan the code, then enter the six-digit code to finish setup.');
      void factors.refetch();
    },
  });
  const verify = useMutation({
    mutationFn: () =>
      run(
        (signal) =>
          verifyMfaFactor({
            client,
            signal,
            body: { factor_id: selected || factors.data?.factors[0]?.id || '', code },
            headers: csrf,
          }),
        sessionSchema,
      ),
    onSuccess: (result) => {
      setCode('');
      setEnrollment(null);
      setNotice('Authenticator verified. You can continue.');
      cache.setQueryData(SESSION_KEY, result);
      void cache.invalidateQueries({ queryKey: ['identity', 'mfa'] });
      try {
        localStorage.setItem('roombook.account.changed', crypto.randomUUID());
      } catch {
        /* Session checks remain active. */
      }
      onVerified?.();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      run(
        (signal) =>
          removeMfaFactor({
            client,
            signal,
            path: { factor_id: id },
            body: { reason },
            headers: csrf,
          }),
        z.object({ message: z.string() }),
      ),
    onSettled: async () => {
      await cache.cancelQueries();
      cache.clear();
      setEnrollment(null);
    },
    onSuccess: (result) => setNotice(result.message),
    onError: (error) => setNotice(`${error.message} Sign in again to check your authenticators.`),
  });
  if (session.isPending) return <p role="status">Checking your session…</p>;
  if (!session.data || session.isError)
    return (
      <div className="sw-account-panel">
        <p>Sign in to manage your authenticator.</p>
        <Link
          to={`/account/login?next=${encodeURIComponent(safeReturnTo(location.pathname + location.search))}`}
        >
          Sign in
        </Link>
        {notice && <p role="status">{notice}</p>}
      </div>
    );
  const busy = enroll.isPending || verify.isPending || remove.isPending;
  const error = factors.error || enroll.error || verify.error || remove.error;
  return (
    <div className="sw-account-panel sw-mfa-panel">
      <ShieldCheck aria-hidden="true" size={28} />
      <p>Use a code from your authenticator app. Administrator access requires this extra check.</p>
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert">
          {error.message}{' '}
          <Button onClick={() => void factors.refetch()}>Refresh authenticators</Button>
        </p>
      )}
      {factors.isPending ? (
        <p role="status">Loading authenticators…</p>
      ) : (
        <>
          {!!factors.data?.factors.length && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                verify.mutate();
              }}
            >
              <label>
                Authenticator
                <select
                  value={selected || factors.data.factors[0]?.id}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  {factors.data.factors.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.friendly_name} · {f.status}
                    </option>
                  ))}
                </select>
              </label>
              {enrollment && (
                <div className="sw-mfa-enrollment">
                  <img
                    src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(enrollment.qr_code)}`}
                    alt="Scan with your authenticator app"
                  />
                  <details>
                    <summary>Enter a setup key instead</summary>
                    <code>{enrollment.secret}</code>
                  </details>
                </div>
              )}
              <label>
                Six-digit code
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </label>
              <Button type="submit" variant="primary" disabled={busy}>
                {verify.isPending ? 'Verifying…' : 'Verify authenticator'}
              </Button>
            </form>
          )}
          {!compact && (
            <details className="sw-mfa-manage" open={!factors.data?.factors.length}>
              <summary>
                <KeyRound size={16} aria-hidden="true" /> Manage authenticators
              </summary>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  enroll.mutate();
                }}
              >
                <label>
                  Authenticator name
                  <input
                    required
                    maxLength={64}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <Button type="submit" disabled={busy || !!enrollment}>
                  Add authenticator
                </Button>
              </form>
              {!!factors.data?.factors.length && (
                <>
                  <p>
                    Removing an authenticator signs you out. Verify again first to remove a verified
                    factor. Admins must keep one verified authenticator.
                  </p>
                  <label>
                    Reason for removal
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      maxLength={500}
                    />
                  </label>
                  <ul>
                    {factors.data.factors.map((f) => (
                      <li key={f.id}>
                        {f.friendly_name} · {f.status}{' '}
                        <Button
                          disabled={
                            busy ||
                            !reason.trim() ||
                            (session.data?.user.role === 'Admin' &&
                              f.status === 'verified' &&
                              factors.data?.factors.filter((item) => item.status === 'verified')
                                .length <= 1)
                          }
                          onClick={() => {
                            if (window.confirm(`Remove ${f.friendly_name} and sign out?`))
                              remove.mutate(f.id);
                          }}
                        >
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </details>
          )}
        </>
      )}
    </div>
  );
}
export function MfaPage() {
  const [params] = useSearchParams();
  const [verified, setVerified] = useState(false);
  return (
    <section>
      <PageTitle
        title="Secure your account"
        description="Your authenticator stays with you. Your account stays protected."
      />
      <MfaPanel onVerified={() => setVerified(true)} />
      {verified && (
        <Link className="sw-btn sw-primary" to={safeReturnTo(params.get('next'))}>
          Continue
        </Link>
      )}
    </section>
  );
}
