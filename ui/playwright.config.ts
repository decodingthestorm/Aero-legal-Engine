import { defineConfig, devices } from "@playwright/test";

// Both servers are started automatically (or reused if already running
// locally — see reuseExistingServer below) so `npm run test:e2e` is a
// single command, not "remember to start two terminals first."
//
// The API's state (statutes, graph, vector index) is in-process and
// shared across every test in the run — tests use unique citations/entity
// ids per test rather than relying on serialization/isolation to avoid
// interfering with each other.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "html",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  // All three run by default (`npm run test:e2e` runs every configured
  // project) — for a faster local iteration loop, filter to one:
  // `npm run test:e2e -- --project=chromium`. CI always runs all three.
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],
  webServer: [
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // Runs from the repo root (cwd: ".."), where pyproject.toml/src/
      // live. Assumes `uvicorn` is on PATH — i.e. the Python venv this
      // repo's own dependencies were installed into is active in whatever
      // shell runs `npm run test:e2e`, same as running the API manually.
      command: "uvicorn legal_engine.api.main:app --port 8000",
      url: "http://localhost:8000/health",
      cwd: "..",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
