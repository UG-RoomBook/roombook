import { expect, type Page, test } from '@playwright/test';

// Core visitor journeys for booking, against the real system. Rooms only open
// within confirmed hours (RB-51); the pipeline confirms Monday–Friday
// 09:00–17:00 for the reference rooms with scripts.set_room_hours before these
// run. Confirming a booking needs a verified account, so these journeys stop
// at the sign-in boundary and prove nothing can be booked without a session.
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

async function search(page: Page, date: string, from: string, until: string) {
  await page.goto('/');
  const form = page.getByRole('form', { name: 'Room search' });
  await form.getByLabel('Date').fill(date);
  await form.getByLabel('From').fill(from);
  await form.getByRole('combobox', { name: 'Until' }).selectOption(until);
  await form.getByLabel('People').selectOption({ label: 'Any size' });
  await form.getByRole('button', { name: 'Find rooms' }).click();
  await expect(page.getByRole('heading', { level: 2, name: /Available rooms/ })).toBeVisible();
}

test('rooms are bookable within opening hours and closed outside them', async ({ page }) => {
  await search(page, weekday(), '10:00', '11:00');
  await expect(page.locator('.sw-count')).toHaveText(/^[1-9]\d* of \d+ available/);
  await expect(page.getByRole('button', { name: /^Book / }).first()).toBeEnabled();

  await search(page, saturday(), '10:00', '11:00');
  await expect(page.locator('.sw-count')).toHaveText(/^0 of \d+ available/);
  await expect(page.getByRole('button', { name: /^Book / })).toHaveCount(0);
});

test('a visitor chooses a room and time and must sign in before confirming', async ({ page }) => {
  const date = weekday();
  await search(page, date, '10:00', '11:00');
  const book = page.getByRole('button', { name: /^Book / }).first();
  const roomName = ((await book.getAttribute('aria-label')) ?? '').replace(/^Book /, '');
  await book.click();

  // The review keeps the exact room and interval the visitor chose.
  await expect(page).toHaveURL(/\/review\?/);
  await expect(page.getByRole('heading', { level: 1, name: 'Review booking' })).toBeVisible();
  const review = page.getByRole('form', { name: 'Confirm room booking' });
  await expect(review.getByRole('heading', { level: 2, name: roomName })).toBeVisible();
  await expect(review).toContainText('Melbourne');
  await expect(page.getByRole('button', { name: 'Confirm booking' })).toHaveCount(0);

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

  const response = await request.post('/api/v1/bookings', {
    data: {
      room_id: roomId,
      starts_at: `${weekday()}T10:00:00+11:00`,
      ends_at: `${weekday()}T11:00:00+11:00`,
    },
    headers: { 'Idempotency-Key': crypto.randomUUID() },
  });
  // 401 sign-in required (Staging), 403 origin/CSRF refused, or 503 where
  // accounts are switched off (Testing). Never a created booking.
  expect([401, 403, 503]).toContain(response.status());
  expect(response.headers()['content-type']).toContain('application/json');
});
