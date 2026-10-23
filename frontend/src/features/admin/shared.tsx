import { adminRetryKey } from './retry';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { ApiError } from '@/shared/api/client';
import { Button } from '@/shared/ui/Button';
import { SESSION_KEY } from '@/features/accounts/api';
import { useAccountSession } from '@/features/accounts/session';
import { MfaPanel } from '@/features/accounts/MfaPage';

export function Status({ children, good = false }: { children: ReactNode; good?: boolean }) {
  return <span className={`ad-status${good ? ' ad-status-good' : ''}`}>{children}</span>;
}
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="ad-empty">
      <p>{children}</p>
    </div>
  );
}
export function ErrorNotice({ error, retry }: { error: Error | null; retry?: () => void }) {
  if (!error) return null;
  return (
    <div role="alert" className="ad-error">
      <p>{error.message}</p>
      {retry && <Button onClick={retry}>Try again</Button>}
    </div>
  );
}
export function QueryState({
  pending,
  error,
  retry,
  children,
}: {
  pending: boolean;
  error: Error | null;
  retry: () => void;
  children: ReactNode;
}) {
  if (pending)
    return (
      <div className="ad-loading" role="status">
        Loading workspace…
      </div>
    );
  if (error) return <ErrorNotice error={error} retry={retry} />;
  return children;
}
export function SearchBox({
  value,
  onSearch,
  placeholder,
}: {
  value: string;
  onSearch: (value: string) => void;
  placeholder: string;
}) {
  return (
    <form
      className="ad-search"
      key={value}
      onSubmit={(e) => {
        e.preventDefault();
        onSearch(String(new FormData(e.currentTarget).get('search') || ''));
      }}
    >
      <label>
        <span className="ad-sr-only">Search</span>
        <input
          name="search"
          maxLength={120}
          defaultValue={value}
          placeholder={placeholder}
          type="search"
        />
      </label>
      <Button type="submit">Search</Button>
    </form>
  );
}
export function Pagination({
  total,
  offset,
  onPage,
}: {
  total: number;
  offset: number;
  onPage: (offset: number) => void;
}) {
  return (
    <nav className="ad-pagination" aria-label="Results pages">
      <span>
        {total
          ? `${Math.min(offset + 1, total)}–${Math.min(offset + 20, total)} of ${total}`
          : '0 results'}
      </span>
      <div>
        <Button disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - 20))}>
          Previous
        </Button>
        <Button disabled={offset + 20 >= total} onClick={() => onPage(offset + 20)}>
          Next
        </Button>
      </div>
    </nav>
  );
}
export function AdminGuard({ children }: { children: ReactNode }) {
  const session = useAccountSession();
  const location = useLocation();
  const next = encodeURIComponent(location.pathname + location.search);
  if (session.isPending) return <p role="status">Checking administrator access…</p>;
  if (session.isError)
    return <ErrorNotice error={session.error} retry={() => void session.refetch()} />;
  if (!session.data)
    return (
      <section className="ad-access">
        <h1 tabIndex={-1}>Sign in to continue</h1>
        <p>Use your administrator account to open this workspace.</p>
        <Link className="sw-btn sw-primary" to={`/account/login?next=${next}`}>
          Sign in
        </Link>
      </section>
    );
  if (session.data.user.role !== 'Admin')
    return (
      <section className="ad-access">
        <h1 tabIndex={-1}>Administrator access required</h1>
        <p>Your account does not have access to this workspace.</p>
        <Link to="/">Back to RoomBook</Link>
      </section>
    );
  if (session.data.aal !== 'aal2' || !session.data.mfa_verified_at)
    return (
      <section className="ad-access">
        <h1 tabIndex={-1}>One more step</h1>
        <p>Verify your authenticator before opening the admin workspace.</p>
        <Link className="sw-btn sw-primary" to={`/account/mfa?next=${next}`}>
          Verify authenticator
        </Link>
      </section>
    );
  return children;
}
export function Dialog({
  title,
  children,
  onClose,
  locked = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  locked?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="ad-dialog"
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        if (!locked) onClose();
      }}
    >
      <div className="ad-dialog-head">
        <h2 id={titleId}>{title}</h2>
        <Button aria-label="Close dialog" disabled={locked} onClick={onClose}>
          Close
        </Button>
      </div>
      {children}
    </dialog>
  );
}
export function ConfirmAction({
  title,
  children,
  action,
  intent,
  onClose,
  onSuccess,
  confirmLabel = 'Confirm change',
}: {
  title: string;
  children: ReactNode;
  action: (csrf: string, key: string) => Promise<unknown>;
  intent: { action: string; target?: string; payload: unknown };
  onClose: () => void;
  onSuccess: () => void;
  confirmLabel?: string;
}) {
  const session = useAccountSession();
  const cache = useQueryClient();
  const [key] = useState(() => crypto.randomUUID());
  const [verified, setVerified] = useState(false);
  const mutation = useMutation({
    mutationFn: async () => {
      const retry = await adminRetryKey(session.data?.user.id ?? '', intent, key);
      const result = await action(session.data?.csrf_token ?? '', retry.key);
      retry.clear();
      return result;
    },
    onError: () => setVerified(false),
    onSuccess: async () => {
      await Promise.all(
        ['admin', 'rooms', 'room-catalog', 'bookings'].map((root) =>
          cache.invalidateQueries({ queryKey: [root] }),
        ),
      );
      void cache.invalidateQueries({ queryKey: SESSION_KEY });
      onSuccess();
    },
  });
  const stepUp =
    mutation.error instanceof ApiError &&
    ['MFA_RECENT_REQUIRED', 'MFA_REQUIRED'].includes(mutation.error.code ?? '');
  const uncertain =
    mutation.isError &&
    (!(mutation.error instanceof ApiError) ||
      !mutation.error.status ||
      mutation.error.status >= 500);
  return (
    <Dialog title={title} onClose={onClose} locked={mutation.isPending || uncertain}>
      {children}
      {stepUp && !verified ? (
        <MfaPanel compact onVerified={() => setVerified(true)} />
      ) : (
        <>
          <ErrorNotice error={stepUp && verified ? null : mutation.error} />
          {verified && (
            <p role="status">Authenticator verified. Review the change and save when ready.</p>
          )}
          {uncertain && (
            <p role="status">
              The outcome is not yet known. Retry this same request to safely recover its result.
            </p>
          )}
          <div className="ad-actions">
            <Button disabled={mutation.isPending || uncertain} onClick={onClose}>
              Keep editing
            </Button>
            <Button
              variant="primary"
              disabled={mutation.isPending || !session.data}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? 'Saving…' : uncertain ? 'Retry same request' : confirmLabel}
            </Button>
          </div>
        </>
      )}
    </Dialog>
  );
}
export function ReasonField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="ad-field">
      <label htmlFor={id}>Reason for change</label>
      <textarea
        id={id}
        aria-describedby={`${id}-hint`}
        required
        maxLength={500}
        rows={3}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Help the team understand this change."
      />
      <span id={`${id}-hint`} className="ad-hint">
        Recorded in activity history.
      </span>
    </div>
  );
}
