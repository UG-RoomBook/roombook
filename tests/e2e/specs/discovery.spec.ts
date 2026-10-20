import { expect, test } from '@playwright/test';

// Journeys through the real React app, FastAPI and PostgreSQL. The pipeline
// seeds the two reference rooms before running them.
const expectedCommit = process.env.EXPECTED_COMMIT ?? '';
const expectedEnvironment = process.env.EXPECTED_ENVIRONMENT ?? '';

function nextWeekday(): string {
  const day = new Date();
  day.setDate(day.getDate() + 7);
  while (day.getDay() === 0 || day.getDay() === 6) day.setDate(day.getDate() + 1);
  return day.toISOString().slice(0, 10);
}

test('the app shows the deployed release and the seeded rooms', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { level: 1, name: 'Find a room' })).toBeVisible();
  await expect(page.getByRole('article', { name: 'The Studio' })).toBeVisible();
  await expect(page.getByRole('article', { name: 'The Forum' })).toBeVisible();

  // The footer reads /version, proving the browser reached this exact build.
  const footer = page.locator('footer');
  if (expectedEnvironment) await expect(footer).toContainText(expectedEnvironment);
  if (expectedCommit) await expect(footer).toContainText(expectedCommit.slice(0, 7));
});

test('a visitor can search an interval and see availability', async ({ page }) => {
  await page.goto('/');
  const search = page.getByRole('form', { name: 'Room search' });

  await search.getByLabel('Date').fill(nextWeekday());
  await search.getByLabel('From').fill('10:00');
  await search.getByLabel('Until').fill('11:00');
  await search.getByLabel('People').selectOption({ label: 'Any size' });
  await search.getByRole('button', { name: 'Find rooms' }).click();

  await expect(page.getByRole('heading', { level: 2, name: /Available rooms/ })).toBeVisible();
  await expect(page.locator('.sw-count')).toHaveText(/\d+ of \d+ available/);
  await expect(page).toHaveURL(/[?&]date=\d{4}-\d{2}-\d{2}/);
});

test('unknown pages return to room search, unknown API paths stay JSON', async ({
  page,
  request,
}) => {
  await page.goto('/no-such-page');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Find a room' })).toBeVisible();

  const response = await request.get('/api/v1/no-such-route');
  expect(response.status()).toBe(404);
  expect(response.headers()['content-type']).toContain('application/json');
});
