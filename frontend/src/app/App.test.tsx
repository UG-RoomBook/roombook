import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { ThemeProvider } from './ThemeProvider';

const runtime = vi.hoisted(() => ({ available: true, error: false }));
vi.mock('@/shared/api/queries', () => ({
  useRuntimeVersion: () => ({
    isError: runtime.error,
    data: runtime.available
      ? { environment: 'test', commit_sha: 'abc123456789', version: '0.1.0' }
      : undefined,
  }),
}));
vi.mock('@/features/rooms/FindRoomPage', () => ({
  FindRoomPage: function FindPage() {
    const navigate = useNavigate();
    const location = useLocation();
    return (
      <section>
        <h1 tabIndex={-1}>Find a room</h1>
        <input aria-label="Search notes" />
        <button onClick={() => void navigate(`/review${location.search}&room_id=studio`)}>
          Choose Studio
        </button>
      </section>
    );
  },
}));
vi.mock('@/features/bookings/ReviewBookingPage', () => ({
  ReviewBookingPage: () => (
    <section>
      <h1 tabIndex={-1}>Review booking</h1>
    </section>
  ),
}));
vi.mock('@/features/bookings/BookingsPage', () => ({
  BookingsPage: () => (
    <section>
      <h1 tabIndex={-1}>Bookings</h1>
    </section>
  ),
}));

function CurrentLocation() {
  const location = useLocation();
  return (
    <output aria-label="Current location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderApp(path = '/?date=2026-10-19&start=13%3A00&end=14%3A00&capacity=4') {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
          <CurrentLocation />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  runtime.available = true;
  runtime.error = false;
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
});

describe('application shell', () => {
  it('preserves room filters through navigation and identifies the review as room discovery', async () => {
    renderApp();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Choose Studio' }));
    expect(screen.getByRole('link', { name: 'Find a room' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Review booking' })).toHaveFocus(),
    );
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'instant' });
    await user.click(screen.getByRole('link', { name: 'Bookings' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Bookings' })).toHaveFocus());
    await user.click(screen.getByRole('link', { name: 'Find a room' }));
    expect(screen.getByLabelText('Current location')).toHaveTextContent('/?capacity=4');
    expect(screen.getByLabelText('Current location')).not.toHaveTextContent('room_id');
  });

  it('changes appearance without resetting navigation or entered input', async () => {
    renderApp();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Search notes'), 'Room preference');
    await user.click(screen.getByRole('button', { name: 'Dark' }));
    expect(screen.getByLabelText('Search notes')).toHaveValue('Room preference');
    expect(screen.getByLabelText('Current location')).toHaveTextContent('capacity=4');
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  it('shows identity returned by the runtime endpoint', () => {
    renderApp();
    expect(screen.getByText('test · abc1234 · 0.1.0')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute(
      'href',
      '#main-content',
    );
  });

  it('returns an unknown route to room discovery', async () => {
    renderApp('/unknown');
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Find a room' })).toBeInTheDocument(),
    );
    expect(screen.getByLabelText('Current location')).toHaveTextContent('/');
  });

  it('does not invent deployment identity when the endpoint is unavailable', () => {
    runtime.available = false;
    renderApp();
    expect(screen.getByText('Runtime identity unavailable')).toBeInTheDocument();
    expect(screen.queryByText(/abc1234/)).not.toBeInTheDocument();
  });

  it('does not show cached identity after a runtime request fails', () => {
    runtime.error = true;
    renderApp();
    expect(screen.getByText('Runtime identity unavailable')).toBeInTheDocument();
    expect(screen.queryByText(/abc1234/)).not.toBeInTheDocument();
  });

  it('labels explicitly enabled development mock data', () => {
    vi.stubEnv('VITE_ENABLE_MOCKS', 'true');
    renderApp();
    expect(screen.getByText('Demo data · test · abc1234 · 0.1.0')).toBeInTheDocument();
    vi.unstubAllEnvs();
  });
});
