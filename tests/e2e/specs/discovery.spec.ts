import { expect, test } from "@playwright/test";

// Journeys through the real React app, FastAPI and PostgreSQL. The pipeline
// seeds the two reference rooms before running them.
const expectedCommit = process.env.EXPECTED_COMMIT ?? "";
const expectedEnvironment = process.env.EXPECTED_ENVIRONMENT ?? "";

function nextWeekday(): string {
  const day = new Date();
  day.setDate(day.getDate() + 7);
  while (day.getDay() === 0 || day.getDay() === 6)
    day.setDate(day.getDate() + 1);
  return day.toISOString().slice(0, 10);
}

test("the app shows the deployed release and the seeded rooms", async ({
  page,
}) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { level: 1, name: "Find a room" }),
  ).toBeVisible();
  await expect(page.getByRole("article", { name: "The Studio" })).toBeVisible();
  await expect(page.getByRole("article", { name: "The Forum" })).toBeVisible();

  // The footer reads /version, proving the browser reached this exact build.
  const footer = page.locator("footer");
  if (expectedEnvironment)
    await expect(footer).toContainText(expectedEnvironment);
  if (expectedCommit)
    await expect(footer).toContainText(expectedCommit.slice(0, 7));
});

test("a visitor chooses a room before viewing its schedule", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.getByLabel("Date")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Choose time for The Studio" })
    .click();
  await expect(page).toHaveURL(/\/rooms\/[0-9a-f-]+/);
  await expect(
    page.getByRole("heading", { name: "Choose time", exact: true }),
  ).toBeVisible();
  const date = nextWeekday();
  const response = await request.get(
    `/api/v1/rooms/10000000-0000-4000-8000-000000000001/availability?date=${date}`,
  );
  expect(response.ok()).toBe(true);
  const day = await response.json();
  expect(day.timezone).toBe("Australia/Melbourne");
  expect(day.slots).toHaveLength(96);
  await page.getByLabel("Date", { exact: true }).fill(date);
  await expect(
    page.getByText("Availability checked. Updates every 30 seconds."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review booking" }),
  ).toBeDisabled();
  const first = day.slots.find(
    (slot: { available: boolean }) => slot.available,
  );
  if (first) {
    await page.locator(`input[name="start"][value="${first.time}"]`).click();
    await expect(
      page.locator(`input[name="start"][value="${first.time}"]`),
    ).toBeChecked();
    await page
      .locator(`input[name="end"][value="${first.valid_ends[0].time}"]`)
      .click();
    await expect(
      page.locator(`input[name="end"][value="${first.valid_ends[0].time}"]`),
    ).toBeChecked();
    await page.getByRole("button", { name: "Review booking" }).click();
    await expect(
      page.getByRole("heading", { name: "Review booking", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Sign in to book" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Change time" }).click();
    await expect(
      page.locator(`input[name="end"][value="${first.valid_ends[0].time}"]`),
    ).toBeChecked();
  } else {
    // Reference rooms intentionally have unconfirmed hours until an operator approves them.
    await expect(
      page.getByRole("heading", { name: "No available starts on this date" }),
    ).toBeVisible();
    await expect(page.locator('input[name="start"]:enabled')).toHaveCount(0);
  }
});

test("unknown pages return to room search, unknown API paths stay JSON", async ({
  page,
  request,
}) => {
  await page.goto("/no-such-page");
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Find a room" }),
  ).toBeVisible();

  const response = await request.get("/api/v1/no-such-route");
  expect(response.status()).toBe(404);
  expect(response.headers()["content-type"]).toContain("application/json");
});
