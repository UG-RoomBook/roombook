import { expect, test } from "@playwright/test";

// Only run writes against the guarded loopback fixture server, never a deployed environment.
test.skip(
  process.env.ROOMBOOK_E2E_FIXTURE !== "1",
  "Requires the isolated PostgreSQL browser fixture",
);
if (
  process.env.ROOMBOOK_E2E_FIXTURE === "1" &&
  process.env.BASE_URL !== "http://127.0.0.1:8011"
)
  throw new Error("Fixture writes require the guarded local test server");
const studio = "10000000-0000-4000-8000-000000000001";
const forum = "10000000-0000-4000-8000-000000000002";
const date = "2026-10-19";

async function choose(
  page: import("@playwright/test").Page,
  room: string,
  start: string,
  end: string,
) {
  await page.goto(`/rooms/${room}?date=${date}`);
  await expect(
    page.getByText("Availability checked. Updates every 30 seconds."),
  ).toBeVisible();
  await page.locator(`input[name="start"][value="${start}"]`).click();
  await expect(
    page.locator(`input[name="start"][value="${start}"]`),
  ).toBeChecked();
  await page.locator(`input[name="end"][value="${end}"]`).click();
  await expect(page.locator(`input[name="end"][value="${end}"]`)).toBeChecked();
  await page.getByRole("button", { name: "Review booking" }).click();
  await expect(
    page.getByRole("heading", { name: "Review booking", exact: true }),
  ).toBeVisible();
}

test("room-first selection, occupied gap, keyboard, refresh and change-time navigation", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Choose time for The Studio" })
    .click();
  await page.getByLabel("Date", { exact: true }).fill(date);
  const start = page.locator('input[name="start"][value="10:00"]');
  await expect(start).toBeEnabled();
  await start.focus();
  await page.keyboard.press("Space");
  await expect(start).toBeChecked();
  await expect(page.locator('input[name="end"][value="10:30"]')).toBeEnabled();
  await expect(page.locator('input[name="end"][value="10:45"]')).toBeEnabled();
  await expect(page.locator('input[name="end"][value="11:00"]')).toBeDisabled();
  await page.locator('input[name="end"][value="10:45"]').click();
  await page.reload();
  await expect(page.locator('input[name="end"][value="10:45"]')).toBeChecked();
  await page.getByRole("button", { name: "Review booking" }).click();
  await expect(
    page.getByRole("button", { name: "Sign in to book" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Change time" }).click();
  await expect(start).toBeChecked();
  for (const theme of ["Light", "Dark"]) {
    await page.getByRole("button", { name: theme, exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      page.getByRole("button", { name: "Review booking" }),
    ).toBeEnabled();
    expect(
      await page
        .locator("body")
        .evaluate((body) => body.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({
      path: `results/room-slots-mobile-${theme.toLowerCase()}.png`,
      fullPage: true,
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({
      path: `results/room-slots-desktop-${theme.toLowerCase()}.png`,
      fullPage: true,
    });
  }
});

test("authenticated confirmation persists one receipt through reload", async ({
  page,
}) => {
  expect((await page.request.post("/__fixture/session")).ok()).toBe(true);
  await choose(page, studio, "13:00", "14:00");
  await page
    .getByRole("button", { name: "Confirm booking", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Booking confirmed" }),
  ).toBeVisible();
  const receipt = await page.locator(".sw-booking-receipt strong").innerText();
  await page.reload();
  await expect(page.locator(".sw-booking-receipt strong")).toHaveText(receipt);
  const response = await page.request.get(
    `/api/v1/rooms/${studio}/availability?date=${date}`,
  );
  expect(
    (await response.json()).slots.find(
      (slot: { time: string }) => slot.time === "13:00",
    ).available,
  ).toBe(false);
});

test("a competing booking refreshes availability and never submits a different interval", async ({
  page,
  browser,
}) => {
  await page.request.post("/__fixture/session");
  await choose(page, forum, "13:00", "14:00");
  const other = await browser.newContext({ baseURL: process.env.BASE_URL });
  try {
    await other.request.post("/__fixture/session");
    const session = await (
      await other.request.get("/api/v1/auth/session")
    ).json();
    const response = await other.request.post("/api/v1/bookings", {
      headers: {
        Origin: process.env.BASE_URL!,
        "X-CSRF-Token": session.csrf_token,
        "Idempotency-Key": crypto.randomUUID(),
      },
      data: {
        room_id: forum,
        starts_at: `${date}T13:00:00+11:00`,
        ends_at: `${date}T14:00:00+11:00`,
      },
    });
    expect(response.status()).toBe(201);
    let writes = 0;
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        request.url().endsWith("/api/v1/bookings")
      )
        writes++;
    });
    await page
      .getByRole("button", { name: "Confirm booking", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "Room no longer available",
    );
    await page.getByRole("button", { name: "Change time" }).click();
    await expect(
      page.locator('input[name="start"][value="13:00"]'),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Review booking" }),
    ).toBeDisabled();
    expect(writes).toBe(1);
  } finally {
    await other.close();
  }
});

test("a lost successful response retries the same saved attempt", async ({
  page,
}) => {
  await page.request.post("/__fixture/session");
  const keys: string[] = [];
  await page.route("**/api/v1/bookings", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort("failed");
    } else await route.continue();
  });
  await choose(page, studio, "15:00", "16:00");
  await page
    .getByRole("button", { name: "Confirm booking", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Booking outcome not confirmed",
  );
  await expect(
    page.getByRole("button", { name: "Change time" }),
  ).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: "Retry saved booking" }).click();
  await expect(
    page.getByRole("heading", { name: "Booking confirmed" }),
  ).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});
