import { defineConfig, devices } from '@playwright/test';

// BASE_URL is the system under test: the candidate in its disposable Testing
// stack (http://localhost:8000 from inside the app container's network) or
// Staging over HTTPS. Never run these against mocks.
const baseURL = process.env.BASE_URL;
if (!baseURL) {
  throw new Error('Set BASE_URL to the RoomBook instance under test.');
}

export default defineConfig({
  testDir: './specs',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: true,
  retries: 0, // a flaky journey is a failing journey
  reporter: [
    ['list'],
    ['junit', { outputFile: 'results/junit.xml' }],
    ['html', { outputFolder: 'results/html', open: 'never' }],
  ],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    timezoneId: 'Australia/Melbourne',
    locale: 'en-AU',
    // Optional: reuse an existing Chromium binary instead of Playwright's download.
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  outputDir: 'results/artifacts',
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
