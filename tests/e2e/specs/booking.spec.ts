import { type APIRequestContext, expect, test } from '@playwright/test';

// Core visitor journeys for booking, against the real system on the Test
// server and on Staging. Rooms open only within confirmed hours (RB-51); the
// pipeline confirms Monday–Friday 09:00–17:00 for the reference rooms with
// scripts.set_room_hours before these run. Confirming a booking needs a
// verified account, so these stop at the sign-in boundary; the signed-in
// journey is covered by room-booking.spec.ts against its isolated fixture.
const environment = process.env.EXPECTED_ENVIRONMENT ?? '';

/** A date (YYYY-MM-DD) `from` days ahead that falls on one of `weekdays` (0 = Sunday). */
function dayAhead(from: number, weekdays: number[]): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + from);
  while (!weekdays.includes(day.getUTCDay())) day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

const weekday = () => dayAhead(7, [1, 2, 3, 4, 5]);
const saturday = () => dayAhead(2, [6]);

/** Melbourne wall-clock time on `date` as an ISO instant with its real offset (AEST or AEDT). */
function melbourne(date: string, time: string): string {
  const noon = new Date(`${date}T12:00:00Z`);
  const name = new Intl.DateTimeFormat('en-AU', {
    timeZone: 'Australia/Melbourne',
    timeZoneName: 'longOffset',
  })
    .formatToParts(noon)
    .find((part) => part.type === 'timeZoneName')?.value;
  const offset = name?.replace('GMT', '') || '+10:00';
  return `${date}T${time}:00${offset}`;
}

async function availability(request: APIRequestContext, date: string, start: string, end: string) {
  const response = await request.get('/api/v1/rooms', {
    params: { starts_at: melbourne(date, start), ends_at: melbourne(date, end) },
  });
  expect(response.ok()).toBeTruthy();
  return ((await response.json()).items as { available?: boolean }[]).map((room) => room.available);
}

test('rooms are bookable within opening hours and closed outside them', async ({ request }) => {
  const open = await availability(request, weekday(), '10:00', '11:00');
  expect(open.some((available) => available === true)).toBeTruthy();

  const closed = await availability(request, saturday(), '10:00', '11:00');
  expect(closed.length).toBeGreaterThan(0);
  expect(closed.every((available) => available === false)).toBeTruthy();
});

test('a visitor chooses a room and time and must sign in before confirming', async ({ page }) => {
  const date = weekday();
  await page.goto('/');
  await page.getByRole('button', { name: 'Choose time for The Studio' }).click();
  await page.getByLabel('Date', { exact: true }).fill(date);
  await expect(page.getByText('Availability checked. Updates every 30 seconds.')).toBeVisible();

  const start = page.locator('input[name="start"][value="10:00"]');
  await expect(start).toBeEnabled();
  await start.click();
  await expect(start).toBeChecked();
  const end = page.locator('input[name="end"][value="11:00"]');
  await expect(end).toBeEnabled();
  await end.click();
  await expect(end).toBeChecked();
  await page.getByRole('button', { name: 'Review booking' }).click();

  // The review keeps the exact room and interval the visitor chose.
  await expect(page.getByRole('heading', { name: 'Review booking', exact: true })).toBeVisible();
  const review = page.getByRole('form', { name: 'Confirm room booking' });
  await expect(review.getByRole('heading', { level: 2, name: 'The Studio' })).toBeVisible();
  await expect(review).toContainText('Melbourne');
  await expect(page.getByRole('button', { name: 'Confirm booking', exact: true })).toHaveCount(0);

  // Without a session the only way forward is signing in; the selection is carried along.
  if (environment === 'staging') {
    await expect(page.getByText('Use a verified, active account.')).toBeVisible();
  }
  await page.getByRole('button', { name: 'Sign in to book' }).click();
  await expect(page).toHaveURL(/\/account\/login\?next=%2Freview%3F/);
  expect(decodeURIComponent(page.url())).toContain(`date=${date}`);
  if (environment === 'staging') {
    await expect(page.getByLabel('Email address')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
  }
});

test('the booking API refuses a request without a signed-in session', async ({ request }) => {
  const rooms = await request.get('/api/v1/rooms');
  expect(rooms.ok()).toBeTruthy();
  const roomId = (await rooms.json()).items[0].id as string;
  const date = weekday();

  const response = await request.post('/api/v1/bookings', {
    data: {
      room_id: roomId,
      starts_at: melbourne(date, '10:00'),
      ends_at: melbourne(date, '11:00'),
    },
    headers: { 'Idempotency-Key': crypto.randomUUID() },
  });
  // 401 sign-in required (Staging), 403 origin/CSRF refused, or 503 where
  // accounts are switched off (Testing). Never a created booking.
  expect([401, 403, 503]).toContain(response.status());
  expect(response.headers()['content-type']).toContain('application/json');
});
