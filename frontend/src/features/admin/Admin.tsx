import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  DoorOpen,
  CalendarClock,
  CalendarDays,
  Users,
  History,
  ArrowLeft,
  Menu,
  ShieldCheck,
} from 'lucide-react';
import { AccountNavigation } from '@/features/accounts/AccountPage';
import { useAccountSession } from '@/features/accounts/session';
import { Button } from '@/shared/ui/Button';
import './admin.css';

const sections = [
  { to: '/admin', label: 'Overview', Icon: LayoutDashboard },
  { to: '/admin/rooms', label: 'Rooms', Icon: DoorOpen },
  { to: '/admin/schedules', label: 'Schedules', Icon: CalendarClock },
  { to: '/admin/bookings', label: 'Bookings', Icon: CalendarDays },
  { to: '/admin/users', label: 'Users', Icon: Users },
  { to: '/admin/activity', label: 'Activity', Icon: History },
];
export function AdminLink() {
  const session = useAccountSession();
  return session.data?.user.role === 'Admin' && !session.isError ? (
    <Link to="/admin">
      <ShieldCheck aria-hidden="true" />
      Admin workspace
    </Link>
  ) : null;
}
export function AdminNavigation() {
  const location = useLocation();
  const session = useAccountSession();
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <div className="ad-nav-toggle">
        <Button
          aria-expanded={expanded}
          aria-controls="admin-navigation"
          onClick={() => setExpanded(!expanded)}
        >
          <Menu aria-hidden="true" />
          Admin navigation
        </Button>
      </div>
      <nav
        id="admin-navigation"
        className={`sw-nav ad-nav${expanded ? ' ad-nav-expanded' : ''}`}
        aria-label="Admin navigation"
      >
        <span className="ad-nav-label">Workspace</span>
        {session.data?.user.role === 'Admin' &&
          sections.map(({ to, label, Icon }) => (
            <Link
              key={to}
              to={to}
              onClick={() => setExpanded(false)}
              aria-current={
                (to === '/admin' ? location.pathname === to : location.pathname.startsWith(to))
                  ? 'page'
                  : undefined
              }
            >
              <Icon aria-hidden="true" />
              {label}
            </Link>
          ))}
        <div className="ad-nav-bottom">
          <Link to="/">
            <ArrowLeft aria-hidden="true" />
            Back to RoomBook
          </Link>
          <AccountNavigation />
        </div>
      </nav>
    </>
  );
}
