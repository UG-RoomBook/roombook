import { CalendarDays, LayoutGrid } from 'lucide-react';
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { RoomBookingPage } from '@/features/rooms/RoomBookingPage';
import { FindRoomPage } from '@/features/rooms/FindRoomPage';
import { ReviewBookingPage } from '@/features/bookings/ReviewBookingPage';
import { BookingsPage } from '@/features/bookings/BookingsPage';
import { AccountNavigation, AccountPage } from '@/features/accounts/AccountPage';
import { useRuntimeVersion } from '@/shared/api/queries';
import { AdminNavigation, AdminLink } from '@/features/admin/Admin';
import { MfaPage } from '@/features/accounts/MfaPage';
import { AppearanceControl } from './AppearanceControl';

const AdminPage = lazy(() =>
  import('@/features/admin/AdminPage').then((module) => ({ default: module.AdminPage })),
);

function RuntimeIdentity() {
  const version = useRuntimeVersion();
  const demo = import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCKS === 'true';
  return (
    <footer className="sw-footer">
      <span>
        {demo ? 'Demo data · ' : ''}
        {version.data && !version.isError
          ? `${version.data.environment} · ${version.data.commit_sha.slice(0, 7)} · ${version.data.version}`
          : 'Runtime identity unavailable'}
      </span>
      <span>Australia/Melbourne</span>
    </footer>
  );
}

export function App() {
  const location = useLocation();
  const isAdmin = location.pathname === '/admin' || location.pathname.startsWith('/admin/');
  const mainRef = useRef<HTMLElement>(null);
  const previousPath = useRef(location.pathname);
  const findActive =
    location.pathname === '/' ||
    location.pathname === '/review' ||
    location.pathname.startsWith('/rooms/');
  const filters = new URLSearchParams(findActive ? location.search : '');
  for (const key of [...filters.keys()])
    if (!['capacity', 'offset'].includes(key)) filters.delete(key);
  const currentSearch = filters.size ? `?${filters.toString()}` : '';
  const [lastSearch, setLastSearch] = useState(currentSearch);
  if (findActive && lastSearch !== currentSearch) setLastSearch(currentSearch);

  useEffect(() => {
    if (previousPath.current !== location.pathname) {
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
      mainRef.current?.querySelector('h1')?.focus({ preventScroll: true });
      previousPath.current = location.pathname;
    }
    document.title = `${location.pathname.startsWith('/admin') ? 'Administration' : location.pathname.startsWith('/account') ? 'Account' : location.pathname.startsWith('/bookings') ? 'Bookings' : location.pathname.startsWith('/review') ? 'Review booking' : location.pathname.startsWith('/rooms/') ? 'Choose time' : 'Find a room'} | RoomBook`;
  }, [location.pathname, location.search]);

  return (
    <div id="rb-swinburne">
      <a className="sw-skip-link" href="#main-content">
        Skip to content
      </a>
      <div className={`sw-shell${isAdmin ? ' ad-shell' : ''}`}>
        <aside className="sw-sidebar">
          <div className="sw-brand">
            <span className="sw-mark" aria-hidden="true">
              Rb.
            </span>
            RoomBook
          </div>
          {isAdmin ? (
            <AdminNavigation />
          ) : (
            <nav className="sw-nav" aria-label="Main navigation">
              <Link to={`/${lastSearch}`} aria-current={findActive ? 'page' : undefined}>
                <LayoutGrid aria-hidden="true" />
                Find a room
              </Link>
              <Link
                to="/bookings"
                aria-current={location.pathname === '/bookings' ? 'page' : undefined}
              >
                <CalendarDays aria-hidden="true" />
                Bookings
              </Link>
              <AccountNavigation />
              <AdminLink />
            </nav>
          )}
        </aside>
        <div className="sw-workspace">
          <header className="sw-top">
            <div className="sw-breadcrumb">
              <span>Campus</span>
              <span aria-hidden="true">/</span>
              <strong>
                {isAdmin
                  ? 'Administration'
                  : location.pathname.startsWith('/account')
                    ? 'Account'
                    : 'Rooms'}
              </strong>
            </div>
            <AppearanceControl />
          </header>
          <main className="sw-main" id="main-content" tabIndex={-1} ref={mainRef}>
            <div className="sw-stage">
              <Routes>
                <Route path="/" element={<FindRoomPage />} />
                <Route path="/rooms/:roomId" element={<RoomBookingPage />} />
                <Route path="/review" element={<ReviewBookingPage />} />
                <Route path="/bookings" element={<BookingsPage />} />
                <Route
                  path="/admin/*"
                  element={
                    <Suspense fallback={<p role="status">Loading admin workspace…</p>}>
                      <AdminPage />
                    </Suspense>
                  }
                />
                <Route path="/account/mfa" element={<MfaPage />} />
                <Route path="/account/*" element={<AccountPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </div>
            <div className="sw-notice" hidden aria-hidden="true" />
            <RuntimeIdentity />
          </main>
        </div>
      </div>
    </div>
  );
}
