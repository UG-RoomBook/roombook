import { expect, test, type Page } from "@playwright/test";

test.skip(
  process.env.ROOMBOOK_ADMIN_FIXTURE !== "1",
  "Requires isolated admin PostgreSQL fixture",
);
if (
  process.env.ROOMBOOK_ADMIN_FIXTURE === "1" &&
  process.env.BASE_URL !== "http://127.0.0.1:8012"
)
  throw new Error("Admin fixture writes require the guarded loopback server");

async function signIn(page: Page, email = "admin@example.com") {
  await page.goto("/account/login?next=%2Fadmin");
  await page.getByLabel("Email address", { exact: true }).fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}
async function admin(page: Page) {
  await signIn(page);
  await expect(
    page.getByRole("heading", { name: "One more step" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Verify authenticator" }).click();
  await page.getByLabel("Six-digit code").fill("123456");
  await page
    .getByRole("button", { name: "Verify authenticator", exact: true })
    .click();
  await page.getByRole("link", { name: "Continue", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "A little room to manage." }),
  ).toBeVisible();
}

test("member isolation and admin MFA gate", async ({ page }) => {
  await signIn(page, "member@example.com");
  await expect(
    page.getByRole("heading", { name: "Administrator access required" }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/admin/overview")).status()).toBe(403);
  await expect(
    page.getByRole("link", { name: "Users", exact: true }),
  ).toHaveCount(0);
});

test("overview and six sections in light, dark and mobile layouts", async ({
  page,
}) => {
  await admin(page);
  for (const theme of ["Light", "Dark"]) {
    await page.getByRole("button", { name: theme, exact: true }).click();
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({
      path: `results/admin-overview-${theme.toLowerCase()}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page
        .locator("body")
        .evaluate((body) => body.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.getByRole("button", { name: "Admin navigation" }).click();
    const navigation = page.getByRole("navigation", {
      name: "Admin navigation",
    });
    await expect(navigation).toBeVisible();
    for (const link of await navigation.getByRole("link").all()) {
      const bounds = await link.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
    }
    await page.screenshot({
      path: `results/admin-mobile-${theme.toLowerCase()}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.getByRole("link", { name: "Rooms", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Rooms", exact: true }),
    ).toBeVisible();
    expect(
      await page
        .locator("body")
        .evaluate((body) => body.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.goto("/admin");
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const section of [
    "Rooms",
    "Schedules",
    "Bookings",
    "Users",
    "Activity",
  ]) {
    await page
      .getByRole("navigation", { name: "Admin navigation" })
      .getByRole("link", { name: section, exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: section, exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Loading workspace…")).toHaveCount(0);
  }
});

test("create inactive room, confirm schedule and activate; recover lost save response", async ({
  page,
}) => {
  await admin(page);
  await page.goto("/admin/rooms/new");
  await page.getByLabel("Room name").fill("Browser study room");
  await page.getByLabel("Location", { exact: true }).fill("Library level 3");
  await page.getByLabel("Capacity", { exact: true }).fill("6");
  await page.getByLabel("Reason for change").fill("New student study space");
  await page.getByRole("button", { name: "Review new room" }).click();
  let key = "";
  let attempts = 0;
  await page.route("**/api/v1/admin/rooms", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts++;
    const next = route.request().headers()["idempotency-key"];
    if (!key) key = next;
    else expect(next).toBe(key);
    const response = await route.fetch();
    if (attempts === 1) await route.abort();
    else await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(
    page.getByText("The outcome is not yet known.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry same request" }).click();
  await expect(
    page.getByRole("heading", { name: "Rooms", exact: true }),
  ).toBeVisible();
  await page.getByRole("searchbox").fill("Browser study room");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const card = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: "Browser study room" }) });
  await expect(card.getByText("Inactive", { exact: true })).toBeVisible();
  await card.getByRole("link", { name: "Opening hours" }).click();
  await page
    .getByRole("button", { name: "Add hours", exact: true })
    .first()
    .click();
  await page.getByLabel("I confirm these opening hours are correct").check();
  await page
    .getByLabel("Reason for change")
    .fill("Hours approved by facilities");
  await page.getByRole("button", { name: "Preview schedule change" }).click();
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(
    page.getByRole("heading", { name: "Schedules", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: "Browser study room" }) })
    .getByRole("link", { name: "Room details" })
    .click();
  await page.getByLabel("Active and visible for booking").check();
  await page.getByLabel("Reason for change").fill("Ready for use");
  await page.getByRole("button", { name: "Preview change" }).click();
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(
    page.getByRole("heading", { name: "Rooms", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("article")
      .filter({
        has: page.getByRole("heading", { name: "Browser study room" }),
      })
      .getByText("Active", { exact: true }),
  ).toBeVisible();
});

test("ongoing booking cancellation and audited reason", async ({ page }) => {
  await admin(page);
  await page.goto("/admin/bookings?status=ongoing");
  await page.getByRole("button", { name: "View booking" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByLabel("Reason for change")
    .fill("Unexpected maintenance in Studio");
  await page.getByRole("button", { name: "Review cancellation" }).click();
  await page
    .getByRole("button", { name: "Cancel booking", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.goto("/admin/activity?search=cancelled");
  await expect(
    page.getByText("Unexpected maintenance in Studio", { exact: true }),
  ).toBeVisible();
});

test("recent MFA step-up preserves proposed access change and requires another click", async ({
  page,
}) => {
  await admin(page);
  await page.request.post("/__fixture/age-mfa");
  await page.goto("/admin/users?search=member");
  await page.getByRole("button", { name: "Manage access" }).click();
  await page.getByLabel("Account active").uncheck();
  await page
    .getByLabel("Reason for change")
    .fill("Temporarily suspended for account review");
  await page.getByRole("button", { name: "Review access change" }).click();
  await page.getByRole("button", { name: "Confirm change" }).click();
  await page.getByLabel("Six-digit code").fill("123456");
  await page
    .getByRole("button", { name: "Verify authenticator", exact: true })
    .click();
  await expect(
    page.getByText(
      "Authenticator verified. Review the change and save when ready.",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("Reason: Temporarily suspended for account review"),
  ).toBeVisible();
  const before = await page.request.get("/api/v1/admin/users?search=member");
  expect((await before.json()).items[0].is_active).toBe(true);
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("Suspended", { exact: true })).toBeVisible();
});

test("access dialogs support keyboard opening, Escape and focus return", async ({ page }) => {
  await admin(page);
  await page.goto("/admin/users?search=colleague");
  const manage = page.getByRole("button", { name: "Manage access" });
  await manage.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Manage access" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(manage).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Reason for change")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(manage).toBeFocused();
});
