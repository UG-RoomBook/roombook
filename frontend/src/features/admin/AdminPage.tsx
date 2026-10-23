import { Navigate, Route, Routes } from 'react-router-dom';
import { AdminGuard } from './shared';
import { OverviewPage, BookingsPage, UsersPage, ActivityPage } from './Operations';
import { RoomEditPage, RoomForm, RoomsPage } from './Rooms';
import { SchedulePage } from './Schedules';

export function AdminPage() {
  return (
    <div className="ad-workspace">
      <AdminGuard>
        <Routes>
          <Route index element={<OverviewPage />} />
          <Route path="rooms" element={<RoomsPage />} />
          <Route path="rooms/new" element={<RoomForm />} />
          <Route path="rooms/:roomId" element={<RoomEditPage />} />
          <Route path="schedules" element={<RoomsPage schedules />} />
          <Route path="schedules/:roomId" element={<SchedulePage />} />
          <Route path="bookings" element={<BookingsPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </AdminGuard>
    </div>
  );
}
